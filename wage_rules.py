"""Pure plausibility and context rules for wage candidates.

The candidate CSV is deliberately a lead list.  Nothing in this module reads
files or treats a dollar sign as proof that the number is a wage.
"""

from __future__ import annotations

from datetime import date
import re


# 2026 US inside-wireman sanity filters, not a source of truth.  A published
# number outside these bands is safer to reject than to present as pay.
JOURNEYMAN_BASE_BOUNDS = (22.0, 85.0)
JOURNEYMAN_PACKAGE_BOUNDS = (30.0, 130.0)
APPRENTICE_HOURLY_BOUNDS = (11.0, 45.0)
APPRENTICE_PCT_BOUNDS = (30.0, 90.0)
TODAY = date(2026, 8, 10)

KINDS = {
    "journeyman_base",
    "journeyman_total_package",
    "apprentice_hourly",
    "apprentice_pct",
    "raise_increment",
    "unknown",
}

_NEGATIVE = re.compile(
    r"\b(?:hotel|motel|inn|room|reservation|nightly|per\s+night|occupancy|"
    r"rental|lodging|hall\s+rent|dues|initiation|assessment|fee|fine|donation|"
    r"raffle|ticket|dinner|golf|scholarship\s+fund|per\s+diem|mileage|parking)\b",
    re.I,
)
_IRRELEVANT_PATH = re.compile(
    r"(?:^|[/_ -])(?:events?|travel|lodging|calendar|newsletters?|obituaries?|"
    r"minutes?|bylaws?|political[-_ ]?action|retirees?)(?:[/_. -]|$)", re.I,
)
_WAGE = re.compile(
    r"\b(?:wage|pay|scale|rate|compensation|earnings)\b|rate\s+of\s+pay|total\s+package|"
    r"per\s+hour|hourly|/\s*hr\b",
    re.I,
)
_TRADE = re.compile(
    r"\b(?:journeyman|journeymen|journeyworker|wireman|wiremen|apprentice|apprentices|jatc)\b|inside\s+wireman",
    re.I,
)
_RAISE = re.compile(r"\b(?:additional|increase|effective)\b|per\s+hour\s*,?\s*effective", re.I)
_MONEY = re.compile(r"\$\s*(-?\d+(?:\.\d{1,2})?)")


def _number(row):
    raw = str(row.get("parsed_value", "") or "").replace(",", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    m = _MONEY.search(str(row.get("matched_text", "")))
    return float(m.group(1)) if m else None


def _kind(row, text):
    match_type = str(row.get("match_type", "") or "").lower()
    lower = text.lower()
    if match_type == "pct_of_journeyman":
        return "apprentice_pct"
    # Apprentice rows take precedence over a broad 'total package' label.  In
    # particular, LU 82's table has base, benefits, and total columns.
    value = _number(row)
    value_token = ""
    if value is not None:
        raw_value = str(row.get("parsed_value", "") or "").strip()
        value_token = rf"\$\s*{re.escape(raw_value or f'{value:g}')}"
    # A compact same-sentence label is more trustworthy than another trade
    # label elsewhere in a clipped table window.
    if value is not None:
        m = re.search(value_token, text, re.I)
        if m:
            prefix = text[max(0, m.start() - 90):m.start()].lower()
            a = max(prefix.rfind("apprentice"), prefix.rfind("1st year"), prefix.rfind("2nd year"),
                    prefix.rfind("3rd year"), prefix.rfind("4th year"), prefix.rfind("5th year"))
            j = max(prefix.rfind("journeyman"), prefix.rfind("journeyworker"), prefix.rfind("wireman"))
            if a >= 0 and a >= j:
                return "apprentice_hourly"
            if j >= 0:
                if "base" in prefix or match_type == "explicit_rate_base_wage":
                    return "journeyman_base"
                if "=" in prefix and "fringe" in lower:
                    return "journeyman_total_package"
                if "pay" in prefix and "fringe" in lower:
                    return "journeyman_base"
                if "package" in lower or "fringe" in lower:
                    return "journeyman_total_package"
                return "journeyman_base"
    if match_type == "explicit_rate_base_wage" or re.search(r"journeyman.{0,35}base\s+(?:wage|rate|pay)|base\s+(?:wage|rate|pay).{0,35}journeyman", lower):
        return "journeyman_base"
    if match_type == "explicit_rate_total_package" or re.search(r"total\s+package|package\s+rate|wage[- ]fringe\s+package|fringes?", lower):
        return "journeyman_total_package"
    return "unknown"


def classify_wage_candidate(row, page_context):
    """Classify one candidate without doing any I/O.

    ``page_context`` should be the bounded text surrounding the hit.  The
    return shape is intentionally stable so it can be used by tests and by
    the reconciliation build.
    """
    context = str(page_context or "").replace("\xa0", " ")
    source = str(row.get("source_file", "") or "")
    combined = f"{context} {source}"
    result = {"admissible": False, "reject_reason": "", "kind": "unknown", "value": _number(row),
              "basis": str(row.get("match_type", "") or "")}

    if _NEGATIVE.search(combined) or re.search(r"lodging", source, re.I):
        result["reject_reason"] = "negative_context"
        return result
    if _IRRELEVANT_PATH.search(source):
        result["reject_reason"] = "irrelevant_page"
        return result
    if value := result["value"]:
        if value < 5 and _RAISE.search(context):
            result["kind"] = "raise_increment"
            result["reject_reason"] = "raise_increment"
            return result
    if not _WAGE.search(context) or not _TRADE.search(context):
        result["reject_reason"] = "insufficient_context"
        return result

    kind = _kind(row, context)
    result["kind"] = kind
    value = result["value"]
    if kind == "unknown" or value is None:
        result["reject_reason"] = "insufficient_context"
        return result

    bounds = {
        "journeyman_base": JOURNEYMAN_BASE_BOUNDS,
        "journeyman_total_package": JOURNEYMAN_PACKAGE_BOUNDS,
        "apprentice_hourly": APPRENTICE_HOURLY_BOUNDS,
        "apprentice_pct": APPRENTICE_PCT_BOUNDS,
    }.get(kind)
    if not bounds or not (bounds[0] <= value <= bounds[1]):
        result["reject_reason"] = "implausible_value"
        return result

    result["admissible"] = True
    return result


_MONTHS = {
    name.lower(): n for n, name in enumerate(
        ("", "January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December")
    ) if name
}
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"


def extract_effective_date(text):
    """Return ``(ISO-ish date, precision)`` from nearby wage text.

    Year and month precision use the first day as a sortable anchor; callers
    must use the precision when displaying it.
    """
    s = str(text or "").replace("\xa0", " ")
    patterns = [
        (rf"\b(?:effective|as\s+of|beginning)\s+({_MONTH})\s+(\d{{1,2}}),?\s+(20\d{{2}})", "day"),
        (r"\b(?:effective|as\s+of|beginning)\s+(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", "day_us"),
        (rf"\b(?:effective|as\s+of|beginning)\s+({_MONTH})\s+(20\d{{2}})\b", "month"),
        (r"\b(?:effective|as\s+of|beginning)\s+(20\d{2})[-/]?(\d{2})[-/]?(\d{2})\b", "day_iso"),
        (rf"\b({_MONTH})\s+(20\d{{2}})\s+(?:wage|pay|rate|scale|rates?)", "month"),
        (r"\b(20\d{2})\s*[-/]\s*20\d{2}\s+(?:wage|pay|rate|scale|rates?)", "year"),
    ]
    for pattern, precision in patterns:
        m = re.search(pattern, s, re.I)
        if not m:
            continue
        try:
            if precision in ("day", "day_us", "day_iso"):
                if m.group(1).isalpha():
                    month, day, year = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
                elif precision == "day_iso":
                    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return f"{year:04d}-{month:02d}-{day:02d}", "day"
            if precision == "month":
                if m.group(1).isdigit():
                    year, month = int(m.group(1)), int(m.group(2))
                else:
                    month, year = _MONTHS[m.group(1).lower()], int(m.group(2))
                return f"{year:04d}-{month:02d}-01", precision
            return f"{int(m.group(1)):04d}-01-01", precision
        except (KeyError, ValueError):
            continue
    return "", "none"


def date_is_recent(effective_date, precision, max_months=36):
    if not effective_date or precision == "none":
        return False
    try:
        y, m, d = (int(x) for x in effective_date.split("-"))
        age = (TODAY.year - y) * 12 + TODAY.month - m
        if d > TODAY.day:
            age -= 1
        return 0 <= age <= max_months
    except (AttributeError, ValueError):
        return False


def format_effective_date(effective_date, precision):
    if not effective_date:
        return ""
    try:
        y, m, d = (int(x) for x in effective_date.split("-"))
        if precision == "year":
            return str(y)
        if precision == "month":
            return date(y, m, 1).strftime("%B %Y")
        return f"{date(y, m, d).strftime('%B')} {d}, {y}"
    except (AttributeError, ValueError):
        return effective_date
