"""Conservative date parsing for the clearly labeled offline simulator."""
import re
from datetime import date


def simulated_date(request):
    if re.search(r"\b(next|this|tomorrow|yesterday)\b|\d{1,2}/\d{1,2}", request, re.IGNORECASE):
        return None
    matches = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", request)
    textual = re.findall(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}\b", request, re.IGNORECASE)
    if len(matches) + len(textual) != 1:
        return None
    try:
        if matches:
            return date.fromisoformat(matches[0]).isoformat()
        month, day, year = textual[0].replace(",", "").split()
        months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
        return date(int(year), months.index(month.lower()) + 1, int(day)).isoformat()
    except ValueError:
        return None
