"""
Shared window-quality predicate. Used by build_window_label_audit.py (the
human-facing audit) and compute_status.py (the resolution logic in round 3
task 3) -- extracted here so the two never drift apart.
"""
import datetime
import re

# Local copy of compute_status._parse_date. Deliberately NOT imported from
# compute_status -- compute_status imports is_suspect_window from this module
# for task 3, and importing back would create a circular import.


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_CLOCK_TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)\b", re.IGNORECASE)
_MONTH_NAME_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
CLOSURE_WORDS = ["closed", "not accepting", "suspended", "no longer accepting", "does not accept"]

# Round 3, task 3: a window whose text is about a TESTING/interview schedule
# rather than an application-intake window (LU 231: "typically one testing
# date each month") must not be treated as a resolvable application window,
# even if it otherwise has clean month fields. Targeted phrase match, not a
# broad "test" keyword ban -- LU 73's "Interviews will be scheduled in the
# first quarter" legitimately describes an application window and must NOT
# be caught by this.
_TESTING_SCHEDULE_RE = re.compile(r"\btest(ing)?\s+date\b", re.IGNORECASE)


def is_suspect_window(w, today=None):
    """Returns (bool suspect, str reason). Reason is a '|'-joined list of every
    matching suspect condition (empty string if none)."""
    if today is None:
        today = datetime.date.today()
    two_years_out = datetime.date(today.year + 2, today.month, today.day)

    precision = w.get("precision", "")
    open_date = w.get("open_date") or ""
    close_date = w.get("close_date") or ""
    open_month = w.get("open_month")
    close_month = w.get("close_month")
    is_annual = bool(w.get("is_recurring_annual"))
    relative_desc = w.get("relative_description") or ""
    evidence = w.get("evidence_quote") or ""
    combined = f"{relative_desc} {evidence}".lower()

    reasons = []

    has_clock = bool(_CLOCK_TIME_RE.search(combined))
    has_month_word = bool(_MONTH_NAME_RE.search(combined))
    has_month_field = open_month is not None or close_month is not None
    if has_clock and not has_month_word and not has_month_field and not open_date and not close_date:
        reasons.append("clock_time_no_calendar_reference")

    if any(k in combined for k in CLOSURE_WORDS):
        reasons.append("relative_description_is_closure")

    if "~~" in evidence or "<del>" in evidence.lower():
        reasons.append("struck_through_date")

    if _TESTING_SCHEDULE_RE.search(combined):
        reasons.append("testing_schedule_not_application")

    if precision == "absolute" and not open_date and not close_date:
        reasons.append("absolute_with_no_dates")

    if precision == "recurring" and not is_annual and open_month is None and close_month is None:
        reasons.append("recurring_not_resolvable")

    od = _parse_date(open_date)
    cd = _parse_date(close_date)
    if od and cd and cd < od:
        reasons.append("close_before_open")

    if od and od > two_years_out:
        reasons.append("open_date_over_2yr_future")
    if cd and cd > two_years_out:
        reasons.append("close_date_over_2yr_future")

    return bool(reasons), "|".join(reasons)
