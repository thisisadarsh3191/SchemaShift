import re

DATE_LIKE_THRESHOLD = 0.8   # a field is "date-like" if at least 80% of its values match a date format

DATE_PATTERNS = {
    "iso_datetime": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"),
    "iso_date": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "slash_date": re.compile(r"\d{2}/\d{2}/\d{4}"),
}

def findDateFormat(value):
    if isinstance(value,bool):return None
    if isinstance(value,int):
        if 946684800000 <= value <= 4102444800000:return "epoch_ms"   # years 2000 to 2100, in milliseconds
        return None
    if isinstance(value,str):
        for name,pattern in DATE_PATTERNS.items():
            if pattern.fullmatch(value):return name
    return None