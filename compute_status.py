"""
Deterministic status computation from observation-only extraction records.

The extraction model outputs observations only (windows[], status_statements[],
page_last_updated) -- it never judges current status. This module turns those
observations into a computed_status, purely in Python, so it can be re-run
daily (or on any cadence) at zero API cost as facts (and "today") change.

computed_status values:
  rolling        a statement describes year-round/continuous intake, and
                 nothing contradicts it
  conflicting    a rolling statement coexists with a closed or reopening
                 statement -- the page (or the extraction) contains
                 contradictory claims and a human must read it; never
                 displayed as a status
  open           today falls inside a dated (absolute) window
  closed_pending today is before a dated window opens (or before a stated
                 reopening date arrives)
  expected_open  a stated reopen date has passed with no newer statement
                 superseding it
  expired_data   the most recent dated window ended, nothing newer
  closed         explicit closure statement, no reopen date or window at all
  unknown        no usable statement or dates

TODO(monitor.py): once monitor.py has hash history for a URL, last_changed
becomes a real floor for days_since_evidence -- it is the only trustworthy
freshness signal in this system (page content can go stale for years without
any date on the page ever changing). When that history exists, days_since_evidence
should be computed as min(evidence-based days, today - last_changed) rather than
purely from stated_effective_date/window dates/page_last_updated as it is now.
Plug that in here, in the days_since_evidence calculation below.
"""
import calendar
import datetime
import re

from window_rules import is_suspect_window

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

# ---------------------------------------------------------------------------
# Round 2, task 1: rolling-statement timing gate.
#
# The extractor is putting application_method content ("Apply through our
# portal") into status_statements labelled statement_type='rolling'. A
# rolling label only counts as real intake-timing evidence if its text
# actually carries temporal language. These word/pattern lists are the
# heuristic surface of that gate -- they are reviewable, tune THESE, not the
# classify_intake() function body, when a real case is misclassified.
# ---------------------------------------------------------------------------

CONTINUOUS_PHRASES = [
    "year round", "year-round", "year long", "year-long", "all year",
    "continuously", "ongoing", "at any time", "anytime", "at all times",
    "always", "no deadline", "open enrollment", "throughout the year",
    "accepted at all times",
    # round 3, task 1 additions
    "every day", "everyday", "all the time", "at any point",
    "on a rolling basis", "rolling basis", "continually", "perpetually",
    "whenever",
]

PERIODIC_INTERVAL_WORDS = ["daily", "weekly", "monthly", "quarterly"]

# round 3, task 1 additions -- plain substring phrases
PERIODIC_PHRASES = [
    "bi-weekly", "biweekly", "semi-monthly", "twice a month",
    "every other week", "business days", "normal business hours",
    "during office hours",
]

# round 3, task 1: classify_intake requires BOTH a temporal token (above) AND
# one of these application-subject tokens. A statement with only a temporal
# token (LU 349: "new hires could start working anytime during the year" --
# that's about when hires START WORK, not whether applications are open) is
# not intake-timing evidence. Requiring the positive subject is more robust
# than trying to enumerate every non-intake subject to exclude.
APPLICATION_SUBJECT_WORDS = [
    "application", "applications", "applicant", "applicants", "apply",
    "applying", "accept applications", "enroll", "enrollment",
    "registration", "register", "sign up", "intake", "take applications",
    "accepting",
]

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAY_ALT = "|".join(_WEEKDAYS)
_WEEKDAY_ABBR_ALT = "mon|tue|tues|wed|thu|thurs|fri|sat|sun"

# "every Wednesday", "each Monday"
_PERIODIC_EVERY_EACH_RE = re.compile(rf"\b(every|each)\s+({_WEEKDAY_ALT})\b")
# bare plural weekday: "Tuesdays", "on Wednesdays"
_PERIODIC_PLURAL_WEEKDAY_RE = re.compile(rf"\b({_WEEKDAY_ALT})s\b")
# weekday ranges: "Monday through Friday", "Mon-Fri", "Mon - Fri"
_PERIODIC_WEEKDAY_RANGE_RE = re.compile(
    rf"\b({_WEEKDAY_ALT}|{_WEEKDAY_ABBR_ALT})\s*(-|through|to)\s*({_WEEKDAY_ALT}|{_WEEKDAY_ABBR_ALT})\b"
)
# nth weekday/day of the month: "third Monday of the month", "first three days of the month"
_PERIODIC_NTH_OF_MONTH_RE = re.compile(
    r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\b[^.]{0,25}\bof\s+(the|each)?\s*month\b"
)
# bare ordinal + weekday, no "of month" required: "first Monday", "third Friday"
_PERIODIC_NTH_WEEKDAY_RE = re.compile(
    rf"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+({_WEEKDAY_ALT})\b"
)


def classify_intake(text):
    """Classify whether a statement's verbatim text carries real intake-timing
    information, or is method/mechanics-only content that happens to be
    labeled 'rolling'. Returns 'continuous', 'periodic', or 'none'.

    Round 3: requires BOTH a temporal token AND an application-subject token
    (APPLICATION_SUBJECT_WORDS) -- a temporal phrase about something other
    than applications (hiring, job start dates, testing dates) is not
    intake-timing evidence.

    This is a keyword/pattern heuristic, not a semantic parse. It is only
    ever used to DEMOTE -- see the round-2 note in compute_status()."""
    low = (text or "").lower()

    has_subject = any(k in low for k in APPLICATION_SUBJECT_WORDS)
    if not has_subject:
        return "none"

    for phrase in CONTINUOUS_PHRASES:
        if phrase in low:
            return "continuous"
    for word in PERIODIC_INTERVAL_WORDS:
        if word in low:
            return "periodic"
    for phrase in PERIODIC_PHRASES:
        if phrase in low:
            return "periodic"
    if _PERIODIC_EVERY_EACH_RE.search(low):
        return "periodic"
    if _PERIODIC_PLURAL_WEEKDAY_RE.search(low):
        return "periodic"
    if _PERIODIC_WEEKDAY_RANGE_RE.search(low):
        return "periodic"
    if _PERIODIC_NTH_OF_MONTH_RE.search(low):
        return "periodic"
    if _PERIODIC_NTH_WEEKDAY_RE.search(low):
        return "periodic"
    return "none"


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _last_day_of_month(month, year):
    return calendar.monthrange(year, month)[1]


def _recurring_window_cycles(w, today):
    """Given ONE recurring window with both open_month/close_month populated,
    return (cycles, inferred) where cycles is a list of (open_date, close_date)
    datetime.date pairs covering the cycle containing/nearest today (prior,
    current, and next year, to safely handle wraps), and inferred is True if
    open_day/close_day had to be filled in (day 1 / last day of month)."""
    open_month = w.get("open_month")
    close_month = w.get("close_month")
    open_day = w.get("open_day")
    close_day = w.get("close_day")

    inferred = open_day is None or close_day is None
    open_day_use = open_day if open_day is not None else 1

    cycles = []
    for year_offset in (-1, 0, 1):
        year = today.year + year_offset
        try:
            od = datetime.date(year, open_month, open_day_use)
        except ValueError:
            continue

        # year-wrap: close month before open month, or same month with close
        # day before open day (only meaningful when days are stated)
        if close_day is not None and open_day is not None:
            wraps = (close_month < open_month) or (close_month == open_month and close_day < open_day)
        else:
            wraps = close_month < open_month
        close_year = year + 1 if wraps else year

        close_day_use = close_day if close_day is not None else _last_day_of_month(close_month, close_year)
        try:
            cd = datetime.date(close_year, close_month, close_day_use)
        except ValueError:
            continue

        cycles.append((od, cd))

    return cycles, inferred


def _resolve_recurring_windows(windows, today):
    """Round 3, task 3. Resolves eligible recurring windows into an
    open/closed_pending determination the same way absolute windows are
    resolved, but only ever at 'medium' confidence -- these are inferred
    from a pattern, not read off a stated date.

    Eligibility (ALL must hold):
      - is_suspect_window(w) is False
      - precision == 'recurring'
      - is_recurring_annual is true, OR both open_month and close_month populated
      - open_month and close_month are both populated (redundant with the
        above for the annual case, but required either way for resolution)

    Returns dict: resolved (bool -- was there >=1 eligible window at all),
    open_now (bool), next_open_date (date or None), inferred (bool -- did the
    deciding cycle need day-of-month inference), source_window (the window
    dict that produced the answer, or None).
    """
    eligible = []
    for w in windows:
        if w.get("precision") != "recurring":
            continue
        suspect, _reason = is_suspect_window(w, today=today)
        if suspect:
            continue
        if not (w.get("is_recurring_annual") or (w.get("open_month") is not None and w.get("close_month") is not None)):
            continue
        if w.get("open_month") is None or w.get("close_month") is None:
            continue
        eligible.append(w)

    if not eligible:
        return {"resolved": False, "open_now": False, "next_open_date": None,
                "inferred": False, "source_window": None}

    # 1. today inside any resolved window wins
    for w in eligible:
        cycles, inferred = _recurring_window_cycles(w, today)
        for od, cd in cycles:
            if od <= today <= cd:
                return {"resolved": True, "open_now": True, "next_open_date": None,
                        "inferred": inferred, "source_window": w}

    # 2. nothing open now -- earliest future occurrence across all eligible windows
    best_next = None
    best_inferred = False
    best_window = None
    for w in eligible:
        cycles, inferred = _recurring_window_cycles(w, today)
        for od, cd in cycles:
            if od > today and (best_next is None or od < best_next):
                best_next = od
                best_inferred = inferred
                best_window = w

    return {"resolved": True, "open_now": False, "next_open_date": best_next,
            "inferred": best_inferred, "source_window": best_window}


def _cap_confidence(confidence, days_since_evidence):
    """Downgrade-only cap on status_confidence based on evidence age. Never
    upgrades a confidence that was already lower than the cap allows.
      days_since_evidence is None (no dated evidence at all) -> cap at medium
      days_since_evidence > 365                              -> cap at low
      days_since_evidence > 180                               -> cap at medium
    """
    if days_since_evidence is None:
        cap = "medium"
    elif days_since_evidence > 365:
        cap = "low"
    elif days_since_evidence > 180:
        cap = "medium"
    else:
        cap = None
    if cap is None:
        return confidence
    if _CONFIDENCE_RANK[cap] < _CONFIDENCE_RANK[confidence]:
        return cap
    return confidence


def compute_status(record, today=None):
    """record: dict with keys 'windows' (list) and 'status_statements' (list),
    optionally 'page_last_updated' (ISO string or None).
    Returns dict: computed_status, status_confidence, days_since_evidence."""
    if today is None:
        today = datetime.date.today()

    windows = record.get("windows") or []
    statements = record.get("status_statements") or []
    page_last_updated = _parse_date(record.get("page_last_updated"))

    dated_windows = [
        w for w in windows
        if w.get("precision") == "absolute" and _parse_date(w.get("open_date"))
    ]
    all_rolling_statements = [s for s in statements if s.get("statement_type") == "rolling"]
    # Round 2, task 1: a rolling label only counts as rolling EVIDENCE if its
    # text carries real temporal information. Method-only statements
    # ("Apply through our portal") are excluded entirely here -- they trigger
    # neither 'rolling' nor 'conflicting'; if nothing else resolves the local
    # it correctly falls through to 'unknown'/'low', the safe answer.
    rolling_statements = [
        s for s in all_rolling_statements
        if classify_intake(s.get("verbatim_text", "")) != "none"
    ]
    closed_statements = [s for s in statements if s.get("statement_type") == "closed"]
    reopening_statements = [s for s in statements if s.get("statement_type") == "reopening"]

    # ---- gather all dated evidence for days_since_evidence ----
    # TODO(monitor.py): fold last_changed in here once available (see module docstring).
    all_dates = []
    for s in statements:
        d = _parse_date(s.get("stated_effective_date"))
        if d:
            all_dates.append(d)
    for w in dated_windows:
        od = _parse_date(w.get("open_date"))
        cd = _parse_date(w.get("close_date"))
        if od:
            all_dates.append(od)
        if cd:
            all_dates.append(cd)
    if page_last_updated:
        all_dates.append(page_last_updated)
    most_recent = max(all_dates) if all_dates else None
    days_since_evidence = (today - most_recent).days if most_recent else None

    recurring_windows = [w for w in windows if w.get("precision") == "recurring"]

    result = _determine_status(
        today, dated_windows, recurring_windows, rolling_statements, closed_statements,
        reopening_statements, most_recent,
    )
    result["status_confidence"] = _cap_confidence(result["status_confidence"], days_since_evidence)
    result["days_since_evidence"] = days_since_evidence
    result["intake_pattern"] = result["intake_pattern"] if result["computed_status"] == "rolling" else ""
    return result


def _determine_status(today, dated_windows, recurring_windows, rolling_statements,
                       closed_statements, reopening_statements, most_recent):
    """Returns a dict: computed_status, status_confidence, intake_pattern,
    next_open_date (ISO string or ''), window_precision_note (''  or
    'month_boundary_inferred'), inferred_window_status (bool -- True if the
    status came from round-3 recurring-window resolution rather than a
    stated date). status_confidence here is BEFORE the caller applies the
    evidence-age cap. rolling_statements has ALREADY passed the task-1
    timing gate -- method-only statements were filtered out by the caller."""

    def result(status, confidence, intake_pattern="", next_open_date=None,
               window_precision_note="", inferred_window_status=False):
        return {
            "computed_status": status,
            "status_confidence": confidence,
            "intake_pattern": intake_pattern,
            "next_open_date": next_open_date.isoformat() if next_open_date else "",
            "window_precision_note": window_precision_note,
            "inferred_window_status": inferred_window_status,
        }

    # 1. CONFLICTING -- a rolling claim coexists with a closed/reopening claim.
    # Do not try to guess which one is current from text; surface it for a human.
    if rolling_statements and (closed_statements or reopening_statements):
        return result("conflicting", "low")

    # 1b. ROLLING -- rolling claim, nothing contradicts it
    if rolling_statements:
        patterns = {classify_intake(s.get("verbatim_text", "")) for s in rolling_statements}
        if "continuous" in patterns:
            intake_pattern = "continuous"
            confidence = "high" if len(rolling_statements) == 1 and not dated_windows else "medium"
        else:
            # every qualifying statement was 'periodic' -- capped at medium, never high
            intake_pattern = "periodic"
            confidence = "medium"
        return result("rolling", confidence, intake_pattern)

    # 2. OPEN -- today inside a dated (absolute) window
    for w in dated_windows:
        od = _parse_date(w.get("open_date"))
        cd = _parse_date(w.get("close_date"))
        if od and od <= today and (cd is None or today <= cd):
            return result("open", "high")

    # 3. CLOSED_PENDING -- future dated window, or a reopening statement not yet arrived
    future_windows = [w for w in dated_windows if _parse_date(w.get("open_date")) > today]
    future_reopenings = [
        s for s in reopening_statements
        if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) > today
    ]
    if future_windows or future_reopenings:
        candidates = [_parse_date(w.get("open_date")) for w in future_windows]
        candidates += [_parse_date(s["stated_effective_date"]) for s in future_reopenings]
        return result("closed_pending", "high", next_open_date=min(candidates))

    # 4. EXPECTED_OPEN -- reopening date has passed and is the most recent evidence
    past_reopenings = [
        s for s in reopening_statements
        if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) <= today
    ]
    if past_reopenings:
        most_recent_reopen = max(_parse_date(s["stated_effective_date"]) for s in past_reopenings)
        if most_recent is None or most_recent == most_recent_reopen:
            return result("expected_open", "medium")

    # 4.5 (round 3, task 3) -- RECURRING WINDOW RESOLUTION. Runs after every
    # rule based on a stated/absolute date (2, 3, 4) and before the fallbacks
    # that assume no further evidence exists (5, 6, 7). Inferred from a
    # pattern, not a stated date -- always capped at medium, never high.
    recur = _resolve_recurring_windows(recurring_windows, today)
    if recur["resolved"]:
        note = "month_boundary_inferred" if recur["inferred"] else ""
        if recur["open_now"]:
            return result("open", "medium", next_open_date=None,
                           window_precision_note=note, inferred_window_status=True)
        else:
            return result("closed_pending", "medium", next_open_date=recur["next_open_date"],
                           window_precision_note=note, inferred_window_status=True)

    # 5. EXPIRED_DATA -- most recent dated window's close has passed, nothing newer
    past_windows_with_close = [
        w for w in dated_windows
        if _parse_date(w.get("close_date")) and _parse_date(w.get("close_date")) < today
    ]
    if past_windows_with_close:
        most_recent_close = max(_parse_date(w["close_date"]) for w in past_windows_with_close)
        if most_recent is None or most_recent == most_recent_close:
            return result("expired_data", "medium")

    # 6. CLOSED -- explicit closure statement, no reopen date/window anywhere
    if closed_statements and not reopening_statements and not dated_windows:
        return result("closed", "high")

    # 7. UNKNOWN
    return result("unknown", "low")


# ---------------------------------------------------------------------------
# Unit tests -- LU 164 (lapsed window), 269 (future window),
# 728 (passed reopen date), 567 (pending reopen)
# ---------------------------------------------------------------------------
import unittest


class TestComputeStatus(unittest.TestCase):
    TODAY = datetime.date(2026, 8, 10)

    def test_lu164_lapsed_window(self):
        # "OPENS AT NOON ON JULY 7, 2026 AND CLOSES AT NOON ON JULY 11, 2026"
        # today (Aug 10) is after the window closed, nothing newer -> expired_data
        record = {
            "windows": [{
                "precision": "absolute", "open_date": "2026-07-07", "close_date": "2026-07-11",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "expired_data")
        self.assertEqual(result["days_since_evidence"], 30)

    def test_lu269_future_window(self):
        # "APPLICATIONS FOR THE 2026 CLASS ARE NOW CLOSED" + 2027 window not yet open
        record = {
            "windows": [{
                "precision": "absolute", "open_date": "2027-01-01", "close_date": "2027-03-31",
            }],
            "status_statements": [{
                "verbatim_text": "APPLICATIONS FOR THE 2026 APPRENTICESHIP CLASS ARE NOW CLOSED.",
                "statement_type": "closed", "stated_effective_date": None,
                "source_url": "https://ibew269.com/apprenticeship/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")

    def test_lu728_passed_reopen_date(self):
        # "closed as of March 9, 2026...will reopen July 1, 2026" -- today is after July 1
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "As of March 9, 2026, online applications are closed.",
                 "statement_type": "closed", "stated_effective_date": "2026-03-09",
                 "source_url": "https://www.ibew728.org/"},
                {"verbatim_text": "We will reopen the applications on July 1, 2026.",
                 "statement_type": "reopening", "stated_effective_date": "2026-07-01",
                 "source_url": "https://www.ibew728.org/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "expected_open")
        self.assertEqual(result["days_since_evidence"], 40)

    def test_lu567_pending_reopen(self):
        # "closed...will reopen November 2nd, 2026" -- today is before Nov 2
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "Applications for IBEW 567 Apprenticeship are closed.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://www.ibew567.com/apprenticeship/"},
                {"verbatim_text": "they will reopen November 2nd, 2026",
                 "statement_type": "reopening", "stated_effective_date": "2026-11-02",
                 "source_url": "https://www.ibew567.com/apprenticeship/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")

    def test_rolling(self):
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "We accept applications year-round.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "rolling")

    def test_open_today_inside_window(self):
        record = {
            "windows": [{"precision": "absolute", "open_date": "2026-08-01", "close_date": "2026-08-31"}],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")

    def test_closed_no_reopen_no_window(self):
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "The apprenticeship list is closed.",
                "statement_type": "closed", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed")

    def test_unknown_no_evidence(self):
        record = {"windows": [], "status_statements": [], "page_last_updated": None}
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")
        self.assertIsNone(result["days_since_evidence"])

    # -- Task 1: conflicting -------------------------------------------------

    def test_conflicting_rolling_and_closed(self):
        # modeled on LU 292: rolling statement(s) alongside closed statement(s)
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "Applications are open year-round for the Apprenticeship program.",
                 "statement_type": "rolling", "stated_effective_date": None,
                 "source_url": "https://example.org/"},
                {"verbatim_text": "Applications are currently closed.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://example.org/"},
                {"verbatim_text": "The list is closed for this cycle.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://example.org/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "conflicting")
        self.assertEqual(result["status_confidence"], "low")

    def test_conflicting_rolling_and_reopening(self):
        # modeled on LU 557: rolling statement alongside a reopening statement
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "Applications are accepted year-round.",
                 "statement_type": "rolling", "stated_effective_date": None,
                 "source_url": "https://example.org/"},
                {"verbatim_text": "We will reopen January 2027.",
                 "statement_type": "reopening", "stated_effective_date": "2027-01-01",
                 "source_url": "https://example.org/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "conflicting")
        self.assertEqual(result["status_confidence"], "low")

    # -- Task 2: confidence capped by evidence age ---------------------------

    def test_rolling_old_evidence_capped_low(self):
        # modeled on LU 194: rolling claim, but the only date on the page is
        # from 2006 -- 7000+ days old -- so "rolling" should not read as high confidence
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "Applications will be taken Monday - Friday, year around.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": "2006-10-31",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "rolling")
        self.assertEqual(result["status_confidence"], "low")
        self.assertGreater(result["days_since_evidence"], 365)

    def test_rolling_no_dates_capped_medium(self):
        # rolling claim, no dated evidence anywhere -> confidence cannot be "high"
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "We accept applications year-round.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "rolling")
        self.assertEqual(result["status_confidence"], "medium")
        self.assertIsNone(result["days_since_evidence"])

    def test_open_inside_window_stays_high(self):
        # recent/current evidence -- confidence cap must not touch this
        record = {
            "windows": [{"precision": "absolute", "open_date": "2026-08-01", "close_date": "2026-08-31"}],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "high")


class TestClassifyIntake(unittest.TestCase):
    def test_continuous_phrasings(self):
        for text in [
            "We accept applications year-round.",
            "Applications for the Apprenticeship Program are accepted year round.",
            "The JATC accepts applications continuously throughout the year.",
            "Applications are open at any time.",
            "Now accepting applications all year!",
            "We accept applications on an ongoing basis with no deadline.",
        ]:
            self.assertEqual(classify_intake(text), "continuous", text)

    def test_periodic_phrasings(self):
        for text in [
            "Applications are accepted daily.",
            "Applications are reviewed weekly.",
            "New applicant cohorts are accepted monthly.",
            "Applications are reviewed quarterly.",
            "We accept applications every Wednesday.",
            "Applications for the Apprenticeship Program are accepted Mondays.",
            "Applications must be filled out in person on the third Monday of each month.",
            "Applications are accepted the first three days of the month.",
            # the three named regex traps
            "All Applications must be submitted in person at the main union hall located at 101 South 7th Street on Tuesdays from 8:00-4:30.",
            "Applications are taken each Wednesday of the month from 1-5 PM.",
            "Apprenticeship Applications: In person on Tuesdays from 9am - 11:30am and 1pm - 4pm.",
        ]:
            self.assertEqual(classify_intake(text), "periodic", text)

    def test_none_method_only_phrasings(self):
        for text in [
            "Applicants Apply Online",
            "create an online account through our website",
            "You will need to create an account on our online application portal provided in the link at the bottom of the page.",
            "Apply through our portal.",
            "All applicants must apply through the online process.",
            "All applications are submitted online only.",
            "Please call our office to request an application.",
            "Applications may be picked up at our address during business hours.",
        ]:
            self.assertEqual(classify_intake(text), "none", text)


class TestRollingTimingGate(unittest.TestCase):
    TODAY = datetime.date(2026, 8, 10)

    def test_method_only_rolling_alone_is_unknown(self):
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "Apply through our portal.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")
        self.assertEqual(result["status_confidence"], "low")
        self.assertEqual(result["intake_pattern"], "")

    def test_method_only_rolling_plus_closed_is_closed_not_conflicting(self):
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "Apply through our portal.",
                 "statement_type": "rolling", "stated_effective_date": None,
                 "source_url": "https://example.org/"},
                {"verbatim_text": "Applications are currently closed.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://example.org/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed")

    def test_continuous_rolling_fresh_is_high(self):
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "We accept applications year-round.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": "2026-08-01",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "rolling")
        self.assertEqual(result["status_confidence"], "high")
        self.assertEqual(result["intake_pattern"], "continuous")

    def test_periodic_rolling_fresh_is_medium(self):
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "Applications are accepted every Wednesday.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": "2026-08-01",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "rolling")
        self.assertEqual(result["status_confidence"], "medium")
        self.assertEqual(result["intake_pattern"], "periodic")

    def test_continuous_rolling_old_evidence_is_low(self):
        # round-2 gate must not undo the round-1 age cap
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "We accept applications year-round.",
                "statement_type": "rolling", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": "2025-07-06",  # 400 days before TODAY
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual((self.TODAY - datetime.date(2025, 7, 6)).days, 400)
        self.assertEqual(result["computed_status"], "rolling")
        self.assertEqual(result["status_confidence"], "low")


class TestClassifyIntakeSubjectRequirement(unittest.TestCase):
    """Round 3, task 1: classify_intake requires BOTH a temporal token AND an
    application-subject token. Real verbatim_text pulled from extraction_v2.csv,
    not invented."""

    def test_temporal_without_subject_is_none(self):
        # LU 349 Miami -- about when hires START WORK, not application status
        text = "However, new hires could start working anytime during the year."
        self.assertEqual(classify_intake(text), "none")

    def test_every_day_with_subject_is_continuous(self):
        # LU 606 Orlando -- "every day" wasn't in the old interval list at all
        text = "We accept applications every day through our online portal."
        self.assertEqual(classify_intake(text), "continuous")

    def test_lu349_application_statement_has_no_temporal_language(self):
        # LU 349's OTHER statement has the subject but no temporal phrase --
        # both of LU 349's rolling statements should fail the gate now
        text = "Applications will be accepted for employment."
        self.assertEqual(classify_intake(text), "none")

    # -- regression protection: 6 locals that must keep classifying 'continuous' --

    def test_regression_lu20_dallas(self):
        text = ("Applicants are interviewed and accepted into the program year-round, "
                "with the process of job placement and on-the-job-training beginning as soon as accepted.")
        self.assertEqual(classify_intake(text), "continuous")

    def test_regression_lu134_chicago(self):
        text = "Registration is ongoing for the Electrical (A) and Communications (C) Programs"
        self.assertEqual(classify_intake(text), "continuous")

    def test_regression_lu22_omaha(self):
        text = ("The Omaha Joint Apprenticeship & Training Committee accepts applications "
                "year-round for the Electricians Apprenticeship, Construction Electrician, "
                "and Construction Wireman programs.")
        self.assertEqual(classify_intake(text), "continuous")

    def test_regression_lu72_waco(self):
        text = "We take in-person appointments for applications year-round for the apprenticeship."
        self.assertEqual(classify_intake(text), "continuous")

    def test_regression_lu158_green_bay(self):
        text = "Applications for the Apprenticeship Program are accepted year-round."
        self.assertEqual(classify_intake(text), "continuous")

    def test_regression_lu915_tampa(self):
        text = "The Tampa Area Electrical JATC is always accepting applications"
        self.assertEqual(classify_intake(text), "continuous")


class TestRecurringWindowResolution(unittest.TestCase):
    """Round 3, task 3. Real window JSON pulled verbatim from
    extraction_v2.csv for each named local, not invented."""
    TODAY = datetime.date(2026, 8, 10)

    def test_lu490_wraps_open_today(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": 6, "open_day": 1,
                "close_month": 5, "close_day": 20, "is_recurring_annual": True,
                "relative_description": "June 1st to May 20th",
                "evidence_quote": "applications are open from June 1st to May 20th",
                "source_url": "https://ibew490.org/apprenticeship/",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "medium")
        self.assertTrue(result["inferred_window_status"])

    def test_lu82_wraps_closed_pending_next_open(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": 9, "open_day": 1,
                "close_month": 6, "close_day": 30, "is_recurring_annual": True,
                "relative_description": "September 1st to June 30th. No Applications in July or August",
                "evidence_quote": "Applications are accepted from September 1st to June 30th. No Applications in July or August",
                "source_url": "https://www.82jatc.com/index.cfm",
            }],
            "status_statements": [],
            "page_last_updated": "2025-02-10",  # real value -- ages this past 365 days, caps confidence at low
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["next_open_date"], "2026-09-01")

    def test_lu305_no_wrap_closed_pending(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": 1, "open_day": 1,
                "close_month": 1, "close_day": 31, "is_recurring_annual": True,
                "relative_description": "",
                "evidence_quote": "Applications will be accepted in the month of January ONLY (January 1 - January 31)",
                "source_url": "https://fortwayneelectricaljatc.org/apply/",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["status_confidence"], "medium")
        self.assertEqual(result["next_open_date"], "2027-01-01")

    def test_lu449_quarterly_one_currently_open(self):
        record = {
            "windows": [
                {"precision": "recurring", "open_month": 1, "open_day": 1, "close_month": 2, "close_day": 28,
                 "is_recurring_annual": True, "relative_description": "1st Quarter Selection: February 28",
                 "evidence_quote": "1st Quarter Selection:February 28", "source_url": "https://www.eijatc.org/applicant-2/"},
                {"precision": "recurring", "open_month": 3, "open_day": 1, "close_month": 5, "close_day": 31,
                 "is_recurring_annual": True, "relative_description": "2nd Quarter Selection: May 31",
                 "evidence_quote": "2nd Quarter Selection:May 31", "source_url": "https://www.eijatc.org/applicant-2/"},
                {"precision": "recurring", "open_month": 6, "open_day": 1, "close_month": 8, "close_day": 30,
                 "is_recurring_annual": True, "relative_description": "3rd Quarter Selection: August 30",
                 "evidence_quote": "3rd Quarter Selection:August 30", "source_url": "https://www.eijatc.org/applicant-2/"},
                {"precision": "recurring", "open_month": 9, "open_day": 1, "close_month": 11, "close_day": 30,
                 "is_recurring_annual": True, "relative_description": "4th Quarter Selection: November 30",
                 "evidence_quote": "4th Quarter Selection:November 30", "source_url": "https://www.eijatc.org/applicant-2/"},
            ],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "medium")

    def test_lu7_months_only_wraps_inferred_note(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": 9, "open_day": None,
                "close_month": 1, "close_day": None, "is_recurring_annual": True,
                "relative_description": "Informational Sessions are held several times from September through January",
                "evidence_quote": "Informational Sessions are held several times from September through January.",
                "source_url": "https://local7jatc.com/applying-and-qualifying-for-an-apprenticeship/",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["next_open_date"], "2026-09-01")
        self.assertEqual(result["window_precision_note"], "month_boundary_inferred")

    def test_lu73_months_only_no_wrap(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": 1, "open_day": None,
                "close_month": 3, "close_day": None, "is_recurring_annual": True,
                "relative_description": "first quarter (January/February/March) each year",
                "evidence_quote": "Interviews will be scheduled in the first quarter (January/February/March) each year",
                "source_url": "https://www.inlandelectrical.org/how-to-apply-2/",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["next_open_date"], "2027-01-01")

    def test_lu231_testing_schedule_rejected_stays_unknown(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": 9, "open_day": None,
                "close_month": 5, "close_day": None, "is_recurring_annual": True,
                "relative_description": "There is typically one testing date each month. (September - May)",
                "evidence_quote": "typically one testing date each month. (September - May)",
                "source_url": "https://scjatc.org/how-to-apply/",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    def test_lu531_office_hours_rejected_stays_unknown(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_month": None, "open_day": None,
                "close_month": None, "close_day": None, "is_recurring_annual": False,
                "relative_description": "Monday - Friday 8:00 a.m. - 4:00 p.m. (excludes lunch hour 12 - 1)",
                "evidence_quote": "Application for Electrical Apprenticeship will be available: Monday - Friday 8:00 a.m. - 4:00 p.m.",
                "source_url": "https://www.ibewlocal531.org/index.cfm?zone=/unionactive/view_article.cfm&HomeID=748907&page=Apprenticeship",
            }],
            "status_statements": [],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
