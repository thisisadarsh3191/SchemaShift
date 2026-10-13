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

def findColumns(value,path:str,notes:Dict[str,Any],pathsRead:tuple):
    if isinstance(value,dict):
        for fieldName,fieldVal in value.items():
            newPath = f"{path}.{fieldName}" if path else fieldName
            pathsRead+=(newPath,)
            findColumns(fieldVal,newPath,notes,pathsRead)
    elif isinstance(value,list):
        if path:
            notes[path]["types"]["list"]+=1
            notes[path]["length"].append(len(value))
        for i in value:
            newPath = f"{path}[]" if path else "[]"
            pathsRead+=(newPath,)
            findColumns(i,newPath,notes,pathsRead)
    elif value is None:
        if path:
            notes[path]["types"]["None"]+=1
    else:
        if path:
            notes[path]["types"][findType(value)]+=1
        if not notes[path]["limit"]:
            



