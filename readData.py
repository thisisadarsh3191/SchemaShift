"""
Reads the sample docs from each collection and tracks which type of data in each column
   

"""
import json
from datetime import datetime
from typing import Any
from collections import defaultdict, Counter
import re

minVal_forCateg = 30
max_num_Categ = 10
categ_ratio = 0.2 #distinct choices/total values - makes it a constraint for categorical values ft.Claude 
minVal_forUnique = 20 #need this many unique values to be considered a primary key-esque column ft.Claude



datePatterns = {
    "isoDate":re.compile(r"\d{4}-\d{2}-\d{2}"),
    "isoDateTime":re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"),
    "slashDate":re.compile(r"\d{2}/\d{2}/\d{4}")
}
def dateFormat(value)->str|None:
    if isinstance(value,int):
        if 946684800000 <= value <= 4102444800000:return "epoch_ms"   # years 2000 to 2100, in milliseconds
        return None
    if isinstance(value,str):
        for formatName,date in datePatterns.items():
            if date.fullmatch(value):return formatName
    return None
checkNumRE = re.compile(r"-?[0-9]+(\.[0-9]+)?")
def checkNumber(numstr:str)->bool:
    return checkNumRE.fullmatch(numstr) is not None

def findType(value)->str:
    if isinstance(value,bool):return "boolean"
    elif isinstance(value, int):return "integer"
    # elif isinstance(value, str):
    #     if value.isnumeric():
    #         return "numeric string"
    #     return "string"
    elif isinstance(value,str):return "string"
    elif isinstance(value, datetime):return "date"
    else:return type(value).__name__

def findColumns(value,path:str,notes:dict[str,Any],pathsRead:set[str]):
    if isinstance(value,dict):
        if path:
            notes[path]["types"]["object"]+=1
        for fieldName,fieldVal in value.items():
            newPath = f"{path}.{fieldName}" if path else fieldName
            pathsRead.add(newPath)
            
            findColumns(fieldVal,newPath,notes,pathsRead)
    elif isinstance(value,list):
        if path:
            notes[path]["types"]["list"]+=1
            notes[path]["listLength"].append(len(value))
        for i in value:
            newPath = f"{path}[]" if path else "[]"
            pathsRead.add(newPath)
            findColumns(i,newPath,notes,pathsRead)
    elif value is None:
        if path:
            notes[path]["types"]["None"]+=1
    else:
        if path:
            notes[path]["types"][findType(value)]+=1
            dateformat = dateFormat(value)
            if dateformat:
                notes[path]["dateFormats"][dateformat]+=1
                if dateformat == "slashDate":
                    first,second = value.split("/")[:2]
                    notes[path]["slashMaxFirst"] = max(notes[path]["slashMaxFirst"],int(first))
                    notes[path]["slashMaxSecond"] = max(notes[path]["slashMaxSecond"],int(second))


            if isinstance(value,str):
                if checkNumber(value):
                    notes[path]["numericStrings"] +=1
                elif len(notes[path]["badStrings"])<5 and value not in notes[path]["badStrings"]:
                    notes[path]["badStrings"].append(value)


        if not notes[path]["limit"]:
            newVal = str(value)if isinstance(value,(list,dict)) else value
            notes[path]["distinct"].add(newVal)
            if len(notes[path]["distinct"])>1000:
                notes[path]["limit"] = True
                notes[path]["distinct"].clear()

def report(notes:dict[str,Any],docCount:int)->dict[str,Any]:
    report = {}

    for path,data in notes.items():
        docsWithField = data["doccount"]
        presence = (round((docsWithField/docCount)*100,2) if docCount>0 else 0.0)

        totalType = sum(data["types"].values())
        typePercent = {}
        for name,count in data["types"].items():
            typePercent[name] = (round((count/totalType)*100,2) if totalType>0 else 0.0)
        isTypesMixed = len(data["types"])>1
        presenceStatus = ("always present" if presence == 100.0 else "not always present")
        fieldData = {
            "Docs with field": docsWithField,
            "Presence Percentage":presence,
            "Presence Status":presenceStatus,
            "Types":typePercent,
            "mixed types":isTypesMixed
        }

        if path.endswith("[]"):
            parentPath = path[:-2]
        elif "." in path:
            parentPath = path.partition(".")[0]
        else:parentPath = ""

        if parentPath:
            parentDocCount = notes[parentPath]["doccount"] if parentPath in notes else docCount
            fieldData["parentPath"] = parentPath
            fieldData["Presence relative to parent"] = (
                round((docsWithField/parentDocCount)*100,2) if parentDocCount>0 else 0.0
            )

        if data["listLength"]:
            length = data["listLength"]
            fieldData["listData"] = {
                "minLen":min(length),
                "maxLen":max(length),
                "avgLen":round(sum(length)/len(length),2)
            }

        if data["dateFormats"]:
            dateCount = sum(data["dateFormats"].values())
            fieldData["dateFormats"] = dict(data["dateFormats"])
            fieldData["date-like"] = (dateCount/totalType) >= 0.8
            if data["dateFormats"]["slashDate"]:
                if data["slashMaxFirst"]>12 and data["slashMaxSecond"]<=12:
                    fieldData["slashOrder"] = "day-first"
                elif data["slashMaxSecond"]>12 and data["slashMaxFirst"]<=12:
                    fieldData["slashOrder"] = "month-first"
                elif data["slashMaxFirst"]>12 and data["slashMaxSecond"]>12:
                    fieldData["slashOrder"] = "inconsistent - needs review"
                else:
                    fieldData["slashOrder"] = "ambiguous - needs review"

        scalarValues = sum(i for name,i in data["types"].items() if name not in ("list","object","None"))
        if scalarValues:
            if data["limit"]:
                fieldData["uniqueness"] = "unknown -too many values to track"
            else:
                fieldData["distinctCount"] = len(data["distinct"])
                if scalarValues<minVal_forUnique:
                    fieldData["uniqueness"] = "Unknown - lower than minimum number of values"
                elif fieldData["distinctCount"] == scalarValues:
                    fieldData["uniqueness"] = "unique"
                else:
                    fieldData["uniqueness"] = "contains duplicates"
        
        if data["numericStrings"]:
            fieldData["numericStrings"] = data["numericStrings"]
        numbers = data["types"]["integer"] + data["types"]["float"]
        if numbers and data["types"]["string"] and not fieldData.get("date-like"):
            if data["numericStrings"] == data["types"]["string"]:
                fieldData["numberConversion"] = "convertible"
            else:
                fieldData["numberConversion"] = "needs review"
                fieldData["unconvertibleExamples"] = data["badStrings"]

        # isCategory = ((not data["limit"]) and (len(data["distinct"])<=10) and (len(data["distinct"])>0))
        isCategory = (
            (not data["limit"])
            and set(data["types"]) - {None} == {"string"}
            and data["types"]["string"]>= minVal_forCateg
            and len(data["distinct"]) <= max_num_Categ
            and len(data["distinct"])>0
            and len(data["distinct"])/(data["types"]["string"]) <= categ_ratio
        )
        if isCategory:
            fieldData["categorical"] = True
            fieldData["distinct"] = sorted(data["distinct"],key=str)#shows a uniform list everytime for same data ft.Claude
        else:
            fieldData["categorical"] = False
        report[path] = fieldData
    return report

def profileData(db:dict,collectionName:list[str],sampleSize:int = 100):
    finalReport={}
    for collection in collectionName:
        notes = defaultdict(lambda: {
            "doccount":0,
            "types":Counter(),
            "distinct":set(),
            "limit":False,
            "listLength":[],
            "dateFormats":Counter(),
            "slashMaxFirst":0,
            "slashMaxSecond":0,
            "numericStrings":0,
            "badStrings":[]
        })

        docs = db.get(collection,[])[:sampleSize]
        countDocs = len(docs)

        for doc in docs:
            docsRead = set()
            findColumns(doc,"",notes,docsRead)

            for path in docsRead:
                notes[path]["doccount"] += 1
        finalReport[collection] = {
            "Total docs sampled":countDocs,
            "Fields":report(notes,countDocs)
        }
                

    return finalReport

##main block
if __name__ == "__main__":
    with open("online_shop_seed_data.json") as f:
        data = json.load(f)

    profile = profileData(data, ["customers", "products", "orders"])

    with open("profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    print("Profile written to profile.json")
