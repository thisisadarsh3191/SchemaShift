"""Deterministic Step 3 schema-candidate generator.
Rules: flatten non-list objects with scalar children; each list becomes a child
table. Types: string=TEXT, integer=INTEGER, float=NUMERIC, boolean=BOOLEAN,
date-like=TIMESTAMP. Convertible mixed numeric/text uses the numeric type;
other mixed types use TEXT and require review. A column is required only at
100% presence; flattened columns also inherit parent optionality. FK coverage
>=100% is strong, >=90% and <100% requires review, and lower coverage is
rejected. Unique indexes are only for primary keys and profile-unique
email/username fields.

Usage: python schema.py [profile.json] [online_shop_seed_data.json] [candidates.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


RULES = {
    "nested_object": "Flatten non-list objects with scalar children; lists become child tables.",
    "type_mapping": {"string": "TEXT", "integer": "INTEGER", "float": "NUMERIC",
                    "boolean": "BOOLEAN", "date-like": "TIMESTAMP",
                    "convertible mixed numeric/text": "numeric type", "mixed needs review": "TEXT"},
    "required_presence_percent": 100.0,
    "foreign_key_thresholds": {"strong_min_percent": 100.0, "review_min_percent": 90.0},
    "unique_index": "Primary keys and profile-unique email/username fields only.",
}

#generates name from plural to singular
def _singular(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    return name[:-1] if name.endswith("s") and not name.endswith("ss") else name

#manual getting child table name from parent tables
def _child_name(collection: str, field: str) -> str:
    known = {("customers", "phone_numbers"): "customer_phones",
            ("products", "tags"): "product_tags", ("orders", "items"): "order_items"}
    return known.get((collection, field), f"{_singular(collection)}_{_singular(field)}")


def _at_path(value: Any, parts: list[str]):
    if not parts:
        yield value
    elif parts[0] == "[]":
        if isinstance(value, list):
            for item in value:
                yield from _at_path(item, parts[1:])
    elif isinstance(value, dict) and parts[0] in value:
        yield from _at_path(value[parts[0]], parts[1:])


def _values(documents: list[dict[str, Any]], path: str) -> list[Any]:
    result: list[Any] = []
    for document in documents:
        result.extend(_at_path(document, path.split(".")))
    return result


def _evidence(field: dict[str, Any]) -> str:
    types = ", ".join(f"{kind} {pct:g}%" for kind, pct in field.get("Types", {}).items())
    return f"presence {field.get('Presence Percentage', 0):g}%; types {types or 'none'}"


def _sql_type(field: dict[str, Any]) -> tuple[str, str, str]:
    types = field.get("Types", {})
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


def _required(field: dict[str, Any]) -> bool:
    return field.get("Presence Percentage", 0) >= RULES["required_presence_percent"]


def generate_candidates(profile: dict[str, Any], seed: dict[str, Any]) -> dict[str, Any]:
    tables, columns, keys, indexes, relations = [], [], [], [], []
    fields_by_collection = {name: data.get("Fields", {}) for name, data in profile.items()}
    children = []

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
            child = {"table": _child_name(collection, path), "parent": collection,
                    "list_path": path, "element_path": element_path, "object_list": is_object}
            children.append(child)
            tables.append({"name": child["table"], "source": f"{collection}.{element_path}",
                        "rule": "list of objects becomes child table" if is_object else "list of plain values becomes child table",
                        "evidence": f"{_evidence(field)}; element types {element.get('Types', {})}",
                        "confidence": "high"})

    # Pass 2: parent columns and flattened scalar object fields.
    for collection in profile:
        fields = fields_by_collection[collection]
        list_names = {child["list_path"] for child in children if child["parent"] == collection}
        for path, field in fields.items():
            if path.endswith("[]") or any(path == p or path.startswith(p + ".") for p in list_names):
                continue
            if "." not in path and "object" in field.get("Types", {}):
                leaves = [(p, f) for p, f in fields.items()
                        if p.startswith(path + ".") and "." not in p[len(path) + 1:]
                        and not ({"object", "list"} & set(f.get("Types", {})))]
                for leaf_path, leaf in leaves:
                    sql_type, rule, confidence = _sql_type(leaf)
                    columns.append({"table": collection, "name": leaf_path.replace(".", "_"),
                                    "source": f"{collection}.{leaf_path}", "sql_type": sql_type,
                                    "required": _required(field) and _required(leaf),
                                    "rule": f"flatten scalar object; {rule}",
                                    "evidence": f"{_evidence(leaf)}; parent presence {field.get('Presence Percentage', 0):g}%",
                                    "confidence": confidence})
                continue
            if "." in path:
                continue
            sql_type, rule, confidence = _sql_type(field)
            columns.append({"table": collection, "name": path, "source": f"{collection}.{path}",
                            "sql_type": sql_type, "required": _required(field), "rule": rule,
                            "evidence": _evidence(field), "confidence": confidence})

    # Child columns and generated IDs.
    for child in children:
        table, parent = child["table"], child["parent"]
        parent_column = f"{_singular(parent)}_id"
        columns.extend([
            {"table": table, "name": "id", "source": child["element_path"], "sql_type": "INTEGER",
            "required": True, "rule": "generated child-table primary key",
            "evidence": "array elements have no _id", "confidence": "high"},
            {"table": table, "name": parent_column, "source": f"{parent}._id", "sql_type": "TEXT",
            "required": True, "rule": "child-to-parent link", "evidence": "one row per list element",
            "confidence": "high"},
        ])
        fields = fields_by_collection[parent]
        if child["object_list"]:
            prefix = child["element_path"] + "."
            for path, field in fields.items():
                if not path.startswith(prefix):
                    continue
                name = path[len(prefix):]
                if "." in name or name.endswith("[]") or ({"object", "list"} & set(field.get("Types", {}))):
                    continue
                sql_type, rule, confidence = _sql_type(field)
                relative = field.get("Presence relative to parent", field.get("Presence Percentage", 0))
                columns.append({"table": table, "name": name, "source": f"{parent}.{path}",
                                "sql_type": sql_type, "required": relative >= 100,
                                "rule": rule, "evidence": f"{_evidence(field)}; list-element presence {relative:g}%",
                                "confidence": confidence})
        else:
            field = fields.get(child["element_path"], {})
            sql_type, rule, confidence = _sql_type(field)
            columns.append({"table": table, "name": _singular(child["list_path"]),
                            "source": f"{parent}.{child['element_path']}", "sql_type": sql_type,
                            "required": True, "rule": f"one row per list value; {rule}",
                            "evidence": _evidence(field), "confidence": confidence})

    # Pass 3: primary keys, uniqueness, parent links, and collection FKs.
    id_sets = {name: {doc.get("_id") for doc in seed.get(name, []) if doc.get("_id") is not None}
            for name in profile}
    for collection, fields in fields_by_collection.items():
        if "_id" in fields:
            keys.append({"table": collection, "column": "_id", "kind": "primary", "references": None,
                        "source": f"{collection}._id", "rule": "_id is primary key",
                        "evidence": _evidence(fields["_id"]), "confidence": "high"})
            indexes.append({"table": collection, "column": "_id", "kind": "unique",
                            "rule": "primary-key index", "evidence": "primary key", "confidence": "high"})
        for name, field in fields.items():
            if name.lower() in {"email", "username"} and field.get("uniqueness") == "unique":
                indexes.append({"table": collection, "column": name, "kind": "unique",
                                "source": f"{collection}.{name}", "rule": "name clue and profile uniqueness",
                                "evidence": f"{field.get('uniqueness')}; {field.get('distinctCount')} distinct values",
                                "confidence": "high"})

    for child in children:
        parent_column = f"{_singular(child['parent'])}_id"
        keys.extend([
            {"table": child["table"], "column": parent_column, "kind": "foreign",
            "references": f"{child['parent']}._id", "source": f"{child['parent']}._id",
            "rule": "child foreign key to parent", "evidence": "each child row belongs to one parent",
            "confidence": "high"},
            {"table": child["table"], "column": "id", "kind": "primary", "references": None,
            "source": child["element_path"], "rule": "generated child primary key",
            "evidence": "array elements have no _id", "confidence": "high"},
        ])
        indexes.extend([
            {"table": child["table"], "column": parent_column, "kind": "regular",
            "rule": "index foreign-key columns", "evidence": "child-to-parent FK", "confidence": "high"},
            {"table": child["table"], "column": "id", "kind": "unique",
            "rule": "primary-key index", "evidence": "generated primary key", "confidence": "high"},
        ])

    for collection, fields in fields_by_collection.items():
        for path in fields:
            if not path.endswith("_id"):
                continue
            targets = [name for name in profile if _singular(name) == path[:-3]]
            if not targets:
                continue
            target = targets[0]
            values = [value for value in _values(seed.get(collection, []), path) if value is not None]
            matches = sum(value in id_sets[target] for value in values)
            coverage = matches / len(values) * 100 if values else 0.0
            if coverage < RULES["foreign_key_thresholds"]["review_min_percent"]:
                continue
            child = next((item for item in children if item["parent"] == collection
                        and path.startswith(item["element_path"] + ".")), None)
            table = child["table"] if child else collection
            column = path[len(child["element_path"]) + 1:] if child else path
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

    return {"rules": RULES, "tables": tables, "columns": columns,
            "keys": keys, "indexes": indexes, "relations": relations}


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    profile_path = Path(args[0]) if args else Path("profile.json")
    seed_path = Path(args[1]) if len(args) > 1 else Path("online_shop_seed_data.json")
    output_path = Path(args[2]) if len(args) > 2 else Path("candidates.json")
    with profile_path.open(encoding="utf-8") as file:
        profile = json.load(file)
    with seed_path.open(encoding="utf-8") as file:
        seed = json.load(file)
    candidates = generate_candidates(profile, seed)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(candidates, file, indent=2, ensure_ascii=False)
        file.write("\n")


if __name__ == "__main__":
    main()
