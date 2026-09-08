"""Deterministic date parsing: full dates only, day first, no timezone guessing."""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from functools import lru_cache
from numbers import Number

import pandas as pd
from openpyxl.utils.datetime import from_excel, WINDOWS_EPOCH

CLAIM_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_COLUMNS = (
    "ADHERENT EFFECTIVE DATE", "ADHERENT DELETION DATE", "EXPIRY DATE",
    "CLAIM DATE", "DISCHARGE DATE",
)
_TIME = re.compile(
    r"(.*?)[T\s]+(\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d{1,9})?)?\s*(?:AM|PM)?)$",
    re.IGNORECASE,
)
_MONTHS = {name: month for month, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"),
    ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
    ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
    ("nov", "november"), ("dec", "december"),
), 1) for name in names}


def _bounded(value: object) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        return pd.NaT
    stamp = stamp.floor("s")
    # The shared Series uses nanosecond precision; reject unsupported ranges.
    if stamp < pd.Timestamp.min or stamp > pd.Timestamp.max:
        return pd.NaT
    return stamp


@lru_cache(maxsize=8192)
def _parse_text(text: str) -> pd.Timestamp:
    text = " ".join(text.strip().split())
    time = datetime.min.time()
    match = _TIME.fullmatch(text)
    if match:
        text, clock = match.groups()
        clock = re.sub(r"[.,](\d{6})\d+", r".\1", clock.replace(",", "."))
        clock = re.sub(r"\s*(AM|PM)$", r" \1", clock.upper())
        formats = ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M",
                   "%I:%M:%S.%f %p", "%I:%M:%S %p", "%I:%M %p")
        for fmt in formats:
            try:
                time = datetime.strptime(clock, fmt).time()
                break
            except ValueError:
                pass
        else:
            return pd.NaT
    # ISO/year-first dates always keep their month/day positions.
    year_first = re.fullmatch(r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})", text)
    day_first = re.fullmatch(r"(\d{1,2})([-/.])(\d{1,2})\2(\d{4})", text)
    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if year_first:
        year, _, month, day = year_first.groups()
    elif day_first:
        day, _, month, year = day_first.groups()
        # An unmistakable month/day source (08/20) can also be normalized.
        # When both positions are <= 12, the agreed day-first policy wins.
        if int(month) > 12 and int(day) <= 12:
            day, month = month, day
    elif compact:
        year, month, day = compact.groups()
    else:
        parts = re.split(r"[\s,./-]+", text.lower())
        if len(parts) == 3 and re.fullmatch(r"\d{4}", parts[0]):
            parts = [parts[2], parts[1], parts[0]]
        if len(parts) != 3 or not re.fullmatch(r"\d{4}", parts[2]):
            return pd.NaT
        year = parts[2]
        if parts[0] in _MONTHS:
            month, day = _MONTHS[parts[0]], parts[1]
        elif parts[1] in _MONTHS:
            day, month = parts[0], _MONTHS[parts[1]]
        else:
            return pd.NaT
        if not re.fullmatch(r"\d{1,2}", str(day)):
            return pd.NaT
    return _bounded(datetime.combine(date(int(year), int(month), int(day)), time))


def parse_date(value: object, epoch: datetime = WINDOWS_EPOCH) -> pd.Timestamp:
    try:
        if pd.isna(value) or isinstance(value, bool):
            return pd.NaT
        if isinstance(value, (datetime, date, pd.Timestamp)):
            return _bounded(value)
        if isinstance(value, str):
            text = value.strip()
            # Five/six digit serial strings occur in CSV exports. Four-digit
            # strings are incomplete years and must not acquire a birthday.
            if re.fullmatch(r"\d{5,6}(?:\.\d+)?", text):
                value = float(text)
            else:
                return _parse_text(text)
        if isinstance(value, Number):
            serial = float(value)
            if not math.isfinite(serial):
                return pd.NaT
            if serial.is_integer() and 10_000_000 <= serial <= 99_999_999:
                return _parse_text(str(int(serial)))
            if not 1 <= serial <= 100_000:
                return pd.NaT
            # Excel's fictional 1900-02-29 cannot become a real calendar date.
            if epoch == WINDOWS_EPOCH and 60 <= serial < 61:
                return pd.NaT
            return _bounded(from_excel(serial, epoch=epoch))
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    return pd.NaT


def parse_mixed_datetime(series: pd.Series, epoch: datetime = WINDOWS_EPOCH) -> pd.Series:
    return pd.Series(
        [parse_date(value, epoch) for value in series],
        index=series.index, dtype="datetime64[ns]",
    )
