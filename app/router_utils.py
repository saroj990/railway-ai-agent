from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def _today() -> date:
    return datetime.now(IST).date()


def _valid(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_date(text: str) -> str | None:
    lower = text.lower()

    if "day after tomorrow" in lower:
        return (_today() + timedelta(days=2)).isoformat()
    if "tomorrow" in lower:
        return (_today() + timedelta(days=1)).isoformat()
    if re.search(r"\btoday\b", lower):
        return _today().isoformat()

    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        return _valid(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if match:
        return _valid(int(match.group(3)), int(match.group(2)), int(match.group(1)))

    match = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\s*,?\s*(\d{{4}})\b", lower)
    if match:
        return _valid(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))

    match = re.search(rf"\b({_MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})\b", lower)
    if match:
        return _valid(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2)))

    return None


def _clean_station(value: str) -> str:
    value = value.strip().strip("\"'“”")
    value = re.sub(r"^(?:the\s+)", "", value, flags=re.I)
    value = re.sub(r"^(?:trains?|train)\s+", "", value, flags=re.I)
    return value.strip(" .,!?")


def extract_route(text: str) -> tuple[str, str] | None:
    patterns = [
        r"\bfrom\s+(.+?)\s+to\s+(.+?)(?=\s+(?:on|for|dated?|departing|leaving)\b|$)",
        r"\bbetween\s+(.+?)\s+and\s+(.+?)(?=\s+(?:on|for|dated?)\b|$)",
        r"\btrains?\s+(.+?)\s+to\s+(.+?)(?=\s+(?:on|for|dated?)\b|$)",
        r"^\s*(.+?)\s+to\s+(.+?)(?=\s+(?:on|for|dated?)\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        origin, destination = _clean_station(match.group(1)), _clean_station(match.group(2))
        if origin and destination and origin.lower() != destination.lower():
            return origin, destination
    return None


def is_compare(text: str) -> bool:
    return bool(re.search(r"\bcompar|\bwhich is (?:faster|better)|\bversus\b|\bvs\.?\b", text))


def is_live(text: str) -> bool:
    return bool(
        re.search(r"\blive\b|\brunning status\b|\blate\b|\bdelay|\bwhere is\b|\bcurrent status\b", text)
    )


def is_fare(text: str) -> bool:
    return bool(
        re.search(r"\bfare|\bprice|\bcost|\bseat|\bberth|\bavailability|\bavailable\b", text)
    )


def is_search(text: str) -> bool:
    return bool(re.search(r"\btrains?\b|\bfind\b|\bsearch\b|\blist\b|\bshow me\b", text))


def is_schedule(text: str) -> bool:
    return bool(
        re.search(
            r"\bschedule\b|\broute\b|\bstops?\b|\bstations?\b|\btiming|\btime ?table\b|\bhalts?\b",
            text,
        )
    )


def is_help(text: str) -> bool:
    return bool(re.search(r"\bhelp\b|\bwhat can you\b|\bhow do i\b|\bwhat do you do\b", text))
