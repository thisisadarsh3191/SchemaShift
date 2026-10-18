import json
from typing import Any,Iterable,Generator

def singular(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith(("sses", "xes", "ches", "shes")):
        return name[:-2]
    if name.endswith("s") and not name.endswith(("ss", "us")):
        return name[:-1]
    return name

def childTableNaming(collection:str,field:str)->str:
    return f"{singular(collection)}_{singular(field)}"

def adaptPath(path:str)->list[str]:
    normaliza = path.replace('[]','.[]')
    return [token for token in normaliza.split('.')if token]

def findChildObjects(value:Any,parts:list[str])->Generator[Any,None,None]:
    if not parts:
        yield value
        return
    current,remParts = parts[0],parts[1:]

    if current == '[]':
        if isinstance(value,Iterable) and not isinstance(value,(str,bytes,dict)):
            for item in value:
                if item is not None:
                    yield from findChildObjects(item,remParts)
    elif isinstance(value,dict) and current in value:
        childValue = value[current]
        if childValue is not None:
            yield from findChildObjects(childValue,remParts)

def Values(docs:list[dict[str,Any]],path:str)->list[Any]:
    token = adaptPath(path)
    result = []

    for doc in docs:
        if isinstance(doc,dict):
            result.extend(findChildObjects(doc,token))
    return result

def diagnostic(field:dict[str,Any])->str:
    types = ", ".join(f"{datatype} - {percent}%" for datatype,percent in field.get("Types",{}).items())
    return f"Presence: {field.get('Presence Percentage',0)}%; types:{types or None}"

def toSQLType(field: dict[str, Any]) -> tuple[str, str, str]:
    #returns (sqldatatype,explanation,confidence)
    types = field.get("Types", {})

    if set(types)<= {"null"}:
        return "TEXT","no non-null values seen; type unknown", "low"
    
    if field.get("date-like"):
        return "TIMESTAMP", "date-like field maps to TIMESTAMP", "high"
    if field.get("mixed types"):
        if field.get("numberConversion") == "convertible" and (types.get("float", 0) or types.get("integer", 0)):
            return ("NUMERIC" if types.get("float", 0) else "INTEGER",
                    "convertible numeric/text values use numeric type", "medium")
        return "TEXT", "mixed types require human review", "low"
    if types.get("float", 0):
        return "NUMERIC", "float maps to NUMERIC", "high"
    if types.get("integer", 0):
        return "INTEGER", "integer maps to INTEGER", "high"
    if types.get("boolean", 0):
        return "BOOLEAN", "boolean maps to BOOLEAN", "high"
    return "TEXT", "string maps to TEXT", "high"

def checkPrimaryKey(field:dict[str,Any])->bool:
    return field.get("Presence Percentage",0) == 100.0


def generateSchema(profile:dict[str,Any],seedData:dict[str,Any]) ->dict[str,Any]:
    tables,columns,keys,indexes,relations = [],[],[],[],[]
    skipped = []
    fields_by_collection = {name:data.get("Fields",{}) for name,data in profile.items()}
    children = []

    #creation of tables
    # Pass 1: collections and child tables for top-level lists.
    for collection, data in profile.items():
        fields = fields_by_collection[collection]
        tables.append({"name": collection, "source": collection,
                    "rule": "top-level collection becomes a table",
                    "evidence": f"{data.get('Total docs sampled', 0)} sampled documents",
                    "confidence": "high"})
        for path, field in fields.items():
            if "." in path or "list" not in field.get("Types", {}):
                continue
            element_path = path + "[]"
            element = fields.get(element_path, {})
            is_object = "object" in element.get("Types", {})
            child = {"table": childTableNaming(collection, path), "parent": collection,
                    "list_path": path, "element_path": element_path, "object_list": is_object}
            children.append(child)
            tables.append({"name": child["table"], "source": f"{collection}.{element_path}",
                        "rule": "list of objects becomes child table" if is_object else "list of plain values becomes child table",
                        "evidence": f"{diagnostic(field)}; element types {element.get('Types', {})}",
                        "confidence": "high"})

    for collection in profile:
        fields = fields_by_collection[collection]

        listNames = {
            child["list_path"] for child in children if child["parent"] == collection
        }

        for path, field in fields.items():
            if path.endswith("[]") or any(path == p or path.startswith(p+".") for p in listNames):
                continue#filtering out array based fields as they have their own childtable
            if "." not in path and "object" in field.get("Types",{}):#finding out top level neseted fields like address
                leaves = [
                    (p,f) for p,f in fields.items() 
                    if p.startswith(path+".") #checks if it is a child objeect eg. 'address.city' and not 'name'
                    and "." not in p[len(path)+1:] #checks if it isnt doubly or more nested eg. address.city.pincode ensures that the object is a leaf and not a branch
                    and not (
                        {"object","list"} & set(f.get("Types",{})) #checks if the type of object is either object or list and removes them
                    )
                ]
                leafPaths = {p for p,leaf in leaves}
                for p in fields:
                    if p.startswith(path+".") and p not in leafPaths:
                        skipped.append({
                            "source":f"{collection}.{p}",
                            "reason":"nested inside one level deep"
                        })
                for leafPath, leaf in leaves:
                    typeSQL,rule,confidence = toSQLType(leaf)
                    columns.append({
                        "table": collection,
                        "name": leafPath.replace(".", "_"),
                        "source": f"{collection}.{leafPath}",
                        "sql_type": typeSQL,
                        "required": checkPrimaryKey(field) and checkPrimaryKey(leaf),
                        "rule": f"flatten scalar object; {rule}",
                        "evidence": f"{diagnostic(leaf)}; parent presence {field.get('Presence Percentage', 0):g}%",
                        "confidence": confidence
                    })
                continue
            if "." in path:continue
            typeSQL,rule,confidence = toSQLType(field)
            columns.append({
                            "table": collection, 
                            "name": path, 
                            "source": f"{collection}.{path}",
                            "sql_type": typeSQL, 
                            "required": checkPrimaryKey(field), 
                            "rule": rule,
                            "evidence": diagnostic(field), 
                            "confidence": confidence
                        })
    for child in children:
        table, parent = child["table"], child["parent"]
        parent_column = f"{singular(parent)}_id"#column for parent foreign key
        columns.extend([
            {"table": table, "name": "id", "source": child["element_path"], "sql_type": "INTEGER",
            "required": True, "rule": "generated child-table primary key",
            "evidence": "array elements have no _id", "confidence": "high"},
            {"table": table, "name": parent_column, "source": f"{parent}._id", "sql_type": toSQLType(fields_by_collection[parent].get("_id",{}))[0],
            "required": True, "rule": "child-to-parent link", "evidence": "one row per list element",
            "confidence": "high"},
        ])
        fields = fields_by_collection[parent]
        if child["object_list"]:
            prefix = child["element_path"] + "."
            for path,field in fields.items():
                if not path.startswith(prefix):
                    continue
                name = path[len(prefix):]
                if "." in name or name.endswith("[]") or ({"object","list"} & set(field.get("Types",{}))):
                    continue
                sql_type, rule, confidence = toSQLType(field)
                relative = field.get("Presence relative to parent")
                required = relative is not None and relative == 100.0


                columns.append({"table": table, "name": name, "source": f"{parent}.{path}",
                                "sql_type": sql_type, "required": required,
                                "rule": rule, "evidence": f"{diagnostic(field)}; list-element presence {relative:g}%",
                                "confidence": confidence})
        else:
            field = fields.get(child["element_path"], {})
            sql_type, rule, confidence = toSQLType(field)
            columns.append({"table": table, "name": singular(child["list_path"]),
                            "source": f"{parent}.{child['element_path']}", "sql_type": sql_type,
                            "required": True, "rule": f"one row per list value; {rule}",
                            "evidence": diagnostic(field), "confidence": confidence})

    idSet = {
        name:{doc.get("_id") for doc in seedData.get(name,[]) if doc.get("_id") is not None}
        for name in profile
    }

    for collection,fields in fields_by_collection.items():
        if "_id" in fields:
            keys.append({"table": collection, "column": "_id", "kind": "primary", "references": None,
                        "source": f"{collection}._id", "rule": "_id is primary key",
                        "evidence": diagnostic(fields["_id"]), "confidence": "high"})
            indexes.append({"table": collection, "column": "_id", "kind": "unique",
            "rule": "primary-key index", "evidence": "primary key", "confidence": "high"})
            for name, field in fields.items():
                if name.lower() in {"email", "username"} and field.get("uniqueness") == "unique":
                    indexes.append({"table": collection, "column": name, "kind": "unique",
                                    "source": f"{collection}.{name}", "rule": "name clue and profile uniqueness",
                                    "evidence": f"{field.get('uniqueness')}; {field.get('distinctCount')} distinct values",
                                    "confidence": "high"})

    for child in children:
        parentColumn = f"{singular(child['parent'])}_id"
        keys.extend([
            {"table": child["table"], "column": parentColumn, "kind": "foreign",
            "references": f"{child['parent']}._id", "source": f"{child['parent']}._id",
            "rule": "child foreign key to parent", "evidence": "each child row belongs to one parent",
            "confidence": "high"},
            {"table": child["table"], "column": "id", "kind": "primary", "references": None,
            "source": child["element_path"], "rule": "generated child primary key",
            "evidence": "array elements have no _id", "confidence": "high"},
        ])
        indexes.extend([
            {"table": child["table"], "column": parentColumn, "kind": "regular",
            "rule": "index foreign-key columns", "evidence": "child-to-parent FK", "confidence": "high"},
            {"table": child["table"], "column": "id", "kind": "unique",
            "rule": "primary-key index", "evidence": "generated primary key", "confidence": "high"},
        ])
    for collection, fields in fields_by_collection.items():
            for path in fields:
                if not path.endswith("_id"):
                    continue
                targets = [name for name in profile if singular(name) == path.split(".")[-1][:-3]]
                if not targets:
                    continue
                target = targets[0]
                values = [value for value in Values(seedData.get(collection, []), path) if value is not None]
                matches = sum(value in idSet[target] for value in values)
                coverage = matches / len(values) * 100 if values else 0.0
                if coverage < 90.0:
                    skipped.append({
                        "source":f"{collection}.{path}",
                        "reason":f"does not meet min. of 90% coverage. Coverage:{coverage:.2f}"
                    })
                    continue

                child = next(
                    (item for item in children if item["parent"] == collection
                     and path.startswith(item["element_path"]+'.')
                     ),
                     None
                )

                table = child["table"] if child else collection
                column = path[len(child["element_path"])+1:] if child else path
                verdict = "strong foreign key" if coverage >= 100 else "candidate foreign key; review orphan values"
                confidence = "high" if coverage >= 100 else "medium"
                evidence = f"{matches}/{len(values)} values match {target}._id ({coverage:.2f}%)"
                keys.append({"table": table, "column": column, "kind": "foreign",
                            "references": f"{target}._id", "source": f"{collection}.{path}",
                            "rule": f"*_id name clue and seed-value check: {verdict}",
                            "evidence": evidence, "confidence": confidence})
                indexes.append({"table": table, "column": column, "kind": "regular",
                                "rule": "index foreign-key columns", "evidence": evidence,
                                "confidence": confidence})
                relations.append({"from": f"{table}.{column}", "to": f"{target}._id",
                                "verdict": verdict, "coverage_percent": round(coverage, 2),
                                "rule": "name clue plus value membership check",
                                "evidence": evidence, "confidence": confidence})       

                
    
    return{
        'tables':tables,
        'columns':columns,
        'keys':keys,
        'indexes':indexes,
        'relations':relations,
        'skipped':skipped,
        
    }

def main():
    profile = ("profile.json")
    seed = ("online_shop_seed_data.json")
    candidates = ("candidates.json")
    with open(profile,encoding="utf-8") as file:
        profile = json.load(file)
    with open(seed,encoding='utf-8') as file:
        seed = json.load(file)
    with open(candidates,"w",encoding= 'utf-8',newline='\n') as file:
        json.dump(generateSchema(profile,seed),file,indent=4,ensure_ascii=False)
        file.write('\n')
    print("Written to ",candidates)


if __name__ == "__main__":
    main()