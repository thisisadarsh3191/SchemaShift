"""
Reads the sample docs from each collection and tracks which type of data in each column
   

"""
import json
from datetime import datetime
from typing import Any

def findType(value)->str:
    if isinstance(value,bool):return "boolean"
    elif isinstance(value, int):return "integer"
    elif isinstance(value, str):return "string"
    elif isinstance(value, datetime):return "date"
    else:return type(value).__name__

def findColumns(value,path:str,notes:dict[str,Any],pathsRead:set[str]):
    if isinstance(value,dict):
        for fieldName,fieldVal in value.items():
            newPath = f"{path}.{fieldName}" if path else fieldName
            pathsRead.add(newPath)
            findColumns(fieldVal,newPath,notes,pathsRead)
    elif isinstance(value,list):
        if path:
            notes[path]["types"]["list"]+=1
            notes[path]["length"].append(len(value))
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
        if not notes[path]["limit"]:
            newVal = str(value)if isinstance(value,(list,dict)) else value
            notes[path]["distinct"].add(newVal)
            if len(notes[path]["distinct"])>50:
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

        if data["listLength"]:
            length = data["listLength"]
            fieldData["listData"] = {
                "minLen":min(length),
                "maxLen":max(length),
                "avgLen":round(sum(length)/len(length),2)
            }
        isCategory = ((not data["limit"]) and (len(data["distinct"]<=10)and (len(data["distinct"])>0)))
        if isCategory:
            fieldData["categorical"] = True
            fieldData["distinct"] = list(data["distinct"])
        else:
            fieldData["categorical"] = False
        report[path] = fieldData
    return report

def profileData(db:dict,collectionName:list[str],sampleSize:int = 100):
    finalReport={}
    for collection in collectionName:
        notes = {
            "doccount":0,
            "types":{},
            "distinct":set(),
            "limit":False,
            "listLength":[]
        }

        docs = db.get(collectionName,[])[:sampleSize]
        countDocs = len(docs)

        for doc in docs:
            docsRead = set()
            findColumns(doc,"",notes,docsRead)

            for path in docsRead:
                try:
                    notes[path]["doccount"] += 1
                except KeyError:
                    notes[path]["document"] = 1
        finalReport[collectionName] = {
            "Total docs sampled":countDocs,
            "Fields":report(notes,countDocs)
        }
                

    return finalReport

##main block
import json
file = "online_shop_seed_data.json"
with open(file) as f:
    data = json.load(f)
profile = profileData(data,["customers","products","orders"])
print(len(profile))
print(profile)




