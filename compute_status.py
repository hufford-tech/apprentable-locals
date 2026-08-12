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


# ---------------------------------------------------------------------------
# Round 4, task 4: three-way scope classification for 'closed' statements.
#
# A closure can be scoped to a period that HASN'T STARTED (future_period --
# implies currently open, e.g. LU 313 "No applications will be accepted in
# September 2026") or to a NAMED COHORT that has ALREADY closed (past_cohort
# -- says nothing about current intake by itself, e.g. LU 488 "Selection of
# applicants for classes beginning September 2026 has closed"). Everything
# else -- including duration words like "until further notice" /
# "indefinitely" / "temporarily" (these describe DURATION, not SCOPE) and
# historical window-closed logs like LU 11's "January 5th, 2026 (APPLICATION
# WINDOW CLOSED)" -- is unscoped and behaves as a plain closure always has.
# ---------------------------------------------------------------------------

MONTH_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_NAME_ALT = "|".join(MONTH_NUM)
# "September 2026", "January 5th, 2026", "September of 2026"
_MONTH_YEAR_RE = re.compile(
    rf"\b({_MONTH_NAME_ALT})\b(?:\s+\d{{1,2}}(?:st|nd|rd|th)?,?)?(?:\s+of)?\s+(\d{{4}})\b",
    re.IGNORECASE,
)

COHORT_WORDS = ["class", "classes", "cohort", "cohorts", "term", "terms",
                "program year", "session", "sessions"]
_PAST_FRAMING_RE = re.compile(
    r"has\s+closed|has\s+passed|deadline[^.]{0,60}passed|selection[^.]{0,60}closed",
    re.IGNORECASE,
)


def classify_closure_scope(text, today):
    """Returns 'future_period', 'past_cohort', or 'unscoped'. See the module
    comment above for definitions and the traps this must not match."""
    low = (text or "").lower()
    m = _MONTH_YEAR_RE.search(text or "")
    my_date = None
    if m:
        my_date = (int(m.group(2)), MONTH_NUM[m.group(1).lower()])
    is_future_month = my_date is not None and my_date > (today.year, today.month)
    has_cohort_word = any(w in low for w in COHORT_WORDS)
    has_past_framing = bool(_PAST_FRAMING_RE.search(low))

    # past_cohort checked first: LU 488's text names both a cohort AND a
    # month that is nominally "future" by bare date comparison (classes
    # beginning September 2026) -- the cohort+deadline-passed framing must
    # win over the plain future-date read, or it would wrongly read as
    # future_period (implying currently open) instead of past_cohort.
    if has_cohort_word and (has_past_framing or my_date is not None):
        return "past_cohort"
    if is_future_month:
        return "future_period"
    return "unscoped"


def _derive_future_period_date(text, today):
    """The 1st of the month named in a future_period closure -- used only to
    populate next_close_date, never for the recency/days_since_evidence math."""
    m = _MONTH_YEAR_RE.search(text or "")
    if not m:
        return None
    year, month = int(m.group(2)), MONTH_NUM[m.group(1).lower()]
    try:
        return datetime.date(year, month, 1)
    except ValueError:
        return None


# Round 4, task 4/5: does some OTHER statement on the record (any type,
# including the closed statement's own text -- see LU 520, where the signal
# is embedded in the closed statement itself) describe the successor
# cohort/term as currently accepting applications, or as explicitly
# not-yet-open/unannounced? Narrow patterns tuned to the two real cases that
# motivated this (LU 488 vs LU 520). Ambiguous language matches neither and
# correctly falls through to 'unknown' rather than guessing which way to
# resolve a past_cohort closure -- that is the demote-safe default.
_SUCCESSOR_FUTURE_RE = re.compile(
    r"when\s+we\s+begin\s+accepting|will\s+announce|not\s+yet\s+accepting|"
    r"has\s+not\s+yet\s+begun|next\s+term\s+will\s+be\s+announced",
    re.IGNORECASE,
)
_SUCCESSOR_ACCEPTING_RE = re.compile(
    r"applications?\s+received\s+will\s+be\s+for\s+consideration|"
    r"currently\s+accepting\s+applications\s+for|now\s+accepting\s+applications\s+for",
    re.IGNORECASE,
)


def _successor_intake_signal(all_statements):
    """Returns (signal, source_statement): signal is 'future', 'accepting', or
    None. 'future' is checked first as the safer read if text ever matched
    both patterns (shouldn't happen given how narrow they are, but a
    demote-safe tie-break costs nothing)."""
    for s in all_statements:
        if _SUCCESSOR_FUTURE_RE.search(s.get("verbatim_text", "")):
            return "future", s
    for s in all_statements:
        if _SUCCESSOR_ACCEPTING_RE.search(s.get("verbatim_text", "")):
            return "accepting", s
    return None, None


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


def _cap_confidence(confidence, days_since_evidence, days_until_next_event=None):
    """Downgrade-only cap on status_confidence based on evidence age. Never
    upgrades a confidence that was already lower than the cap allows.
      days_since_evidence is None AND days_until_next_event is None
                                     (no dated evidence at all)  -> cap medium
      days_since_evidence > 365                                  -> cap low
      days_since_evidence > 180                                  -> cap medium

    Round 4, task 1: days_since_evidence can now be None for a DIFFERENT
    reason than "no evidence exists" -- a record can have solid, specific,
    dated evidence that just happens to be entirely in the future (LU 150's
    reopening date, LU 112's closing date). That is not staleness; it is the
    opposite. The "no evidence at all" cap must only fire when BOTH days
    values are None -- otherwise LU 150's closed_pending/high (driven by a
    concrete, specific reopen date) would get wrongly capped to medium purely
    because days_since_evidence, now correctly, doesn't retroactively invent
    a past-evidence date that doesn't exist. Before round 4 this worked out
    to the "right" answer only by accident: the old unified max let a future
    date go negative and silently skip every cap branch.
    """
    if days_since_evidence is None and days_until_next_event is None:
        cap = "medium"
    elif days_since_evidence is not None and days_since_evidence > 365:
        cap = "low"
    elif days_since_evidence is not None and days_since_evidence > 180:
        cap = "medium"
    else:
        cap = None
    if cap is None:
        return confidence
    if _CONFIDENCE_RANK[cap] < _CONFIDENCE_RANK[confidence]:
        return cap
    return confidence


def _evidence_recency(statements, dated_windows, page_last_updated, today, embedded_evidence_dates=None):
    """Round 4, task 1. Splits evidence RECENCY (how stale is what we know)
    from evidence TIMING (a future date is real information, just not
    recency):
      days_since_evidence: today minus the most recent dated evidence that is
        NOT in the future. None when there is no such (past) evidence.
      days_until_next_event: the soonest future dated evidence minus today,
        or None.

    Stated dates (status_statements' stated_effective_date + absolute dated
    windows' open/close dates, plus round 5's embedded dates lifted from
    open-statement prose) are the pool whenever any exist; a page's crawl
    timestamp (page_last_updated) is used ONLY as a fallback when there are
    no stated dates at all, past or future. Mixing a stale page-crawl
    timestamp in with a specific future claim would misrepresent how fresh
    THAT claim is -- see LU 112: its only stated dates are two closed
    statements dated Oct 1 (future); its page_last_updated (Jul 8, in the
    past) must not quietly supply a days_since_evidence value the specific
    claims don't support. None is the honest answer until Oct 1 arrives.
    """
    stated_dates = []
    for s in statements:
        d = _parse_date(s.get("stated_effective_date"))
        if d:
            stated_dates.append(d)
    for w in dated_windows:
        od = _parse_date(w.get("open_date"))
        cd = _parse_date(w.get("close_date"))
        if od:
            stated_dates.append(od)
        if cd:
            stated_dates.append(cd)
    if embedded_evidence_dates:
        stated_dates.extend(embedded_evidence_dates)

    pool = stated_dates if stated_dates else ([page_last_updated] if page_last_updated else [])
    past = [d for d in pool if d <= today]
    future = [d for d in pool if d > today]
    days_since = (today - max(past)).days if past else None
    days_until = (min(future) - today).days if future else None
    return days_since, days_until


def compute_status(record, today=None):
    """record: dict with keys 'windows' (list) and 'status_statements' (list),
    optionally 'page_last_updated' (ISO string or None).
    Returns dict: computed_status, status_confidence, days_since_evidence,
    days_until_next_event, next_open_date, next_close_date,
    corroborated_by_unknown_stmt, admitted_statement_count,
    rejected_statement_count, and the other fields _determine_status sets."""
    # Round 5, task 1/3: deferred (function-body, not module-level) import to
    # break the circular dependency regardless of which module a caller
    # imports first -- statement_evidence.py reads classify_intake /
    # classify_closure_scope / APPLICATION_SUBJECT_WORDS / MONTH_NUM /
    # _PAST_FRAMING_RE from THIS module, and this module needs
    # admit_statement FROM statement_evidence.py. A module-level import here
    # only resolves when compute_status.py happens to load first; deferring
    # it into the function body makes both import orders work.
    from statement_evidence import (
        admit_statement, REOPEN_ANNOUNCEMENT_IN_CLOSED_RE,
        dedupe_statements, statement_labels,
    )

    if today is None:
        today = datetime.date.today()

    windows = record.get("windows") or []
    # Round 6, task 4: collapse statements that are the same sentence emitted
    # under more than one statement_type label (LU 567) before anything else
    # reads them -- two copies of one sentence must not be counted as two
    # independent pieces of evidence.
    statements, _dedup_audit_rows = dedupe_statements(record.get("status_statements") or [])
    page_last_updated = _parse_date(record.get("page_last_updated"))

    dated_windows = [
        w for w in windows
        if w.get("precision") == "absolute" and _parse_date(w.get("open_date"))
    ]

    # ---- round 5, task 3: every statement passes through the admissibility
    # gate before any branch below reads it. Nothing after this point touches
    # a raw statement dict -- every list is built from `evidence`. ----
    evidence = [(s, admit_statement(s, today)) for s in statements]
    admitted = [(s, ev) for s, ev in evidence if ev["admissible"]]
    admitted_statement_count = len(admitted)
    rejected_statement_count = len(evidence) - admitted_statement_count
    # Task 2: true whenever an ADMITTED statement's own embedded date
    # contradicts its own text's claim (LU 26: "currently being accepted"
    # sitting next to a deadline that already passed). The verification
    # worklist signal this round exists to produce.
    embedded_date_conflict = any(ev["embedded_date_conflict"] for s, ev in admitted)

    # ---- round 6, task 3: LU 130. A reopening-labeled statement REJECTED by
    # the gate (too vague to count as reopening EVIDENCE -- "Please contact
    # the office in January 2027 for information regarding the 2027-2028
    # school year" has no application-subject vocabulary) still carries a
    # real date in its own text. That date is a fact independent of whether
    # the sentence survives the gate as evidence, so it is surfaced
    # separately and consumed ONLY by rule 7 (CLOSED) below -- the one place
    # a bare closure statement with no admitted reopening/window evidence
    # would otherwise report no next_open_date at all. This never changes
    # WHICH rule fires (rule 7's own guard, "not reopening_statements",
    # already required this statement to be gate-rejected before rule 7 is
    # reachable), so it cannot promote any record rule 7 wasn't already
    # going to resolve as closed.
    rejected_reopening_next_open = None
    rejected_reopening_month_inferred = False
    for s, ev in evidence:
        if ev["admissible"] or "reopening" not in statement_labels(s):
            continue
        for b in ev["embedded_bounds"]:
            if b["role"] == "cohort" or b["date"] <= today:
                continue
            if rejected_reopening_next_open is None or b["date"] < rejected_reopening_next_open:
                rejected_reopening_next_open = b["date"]
                rejected_reopening_month_inferred = b["month_inferred"]

    # Rolling: preserved EXACTLY as round 1-4 left it (task 3 requirement) --
    # gated on statement_type == 'rolling' AND classify_intake(text) != 'none'.
    # Deliberately NOT routed through admit_statement's asserts field: a
    # vague, temporally-flavored sentence sitting in an 'unknown'-typed
    # statement (LU 112's "AVAILABLE as needed throughout the year") must not
    # be promoted into rolling evidence just because its words overlap the
    # continuous-phrase list -- that would demote 'open' to 'conflicting'
    # against an explicit round-4 regression guard, an unintended side effect
    # this round's "text over label" principle was never meant to cause.
    all_rolling_statements = [s for s in statements if "rolling" in statement_labels(s)]
    rolling_statements = [
        s for s in all_rolling_statements
        if classify_intake(s.get("verbatim_text", "")) != "none"
    ]

    # ---- round 5, tasks 1-2: THE fix. Every failing record in this round's
    # spec was mislabeled statement_type == 'open' -- that is the entire
    # demonstrated defect (the round-2 bug reappearing in a new type).
    # open_statements is therefore routed through the full gate: it must
    # still BE labeled 'open' (an unrelated statement's text is not pulled in
    # just because it happens to use "accept"/"open" words -- LU 428/474's
    # 'rolling'-labeled, non-temporal "applications are accepted online
    # only..." text stays out, matching its pre-round-5 'unknown' result) AND
    # pass admit_statement's admissibility + asserts=='open' check.
    #
    # Round 6, task 2 now routes closed_statements and reopening_statements
    # through admit_statement too -- see the comment on closed_label_pool
    # below for what changed and why, and the compute_status() comment on
    # rejected_reopening_next_open for how LU 130's rule-7 block (a vague,
    # gate-rejected reopening statement must still block promotion out of
    # 'unknown' the same way it always has) survives that change.
    open_label_pool = [(s, ev) for s, ev in admitted if "open" in statement_labels(s)]
    raw_open_evidence = [(s, ev) for s, ev in open_label_pool if ev["asserts"] == "open"]

    # ---- round 6, task 2: closed/reopening now pass through the same
    # admissibility gate as 'open' (no_application_subject/method_only/
    # cta_only/office_hours/program_mismatch), so LU 613's "Journeyman Wireman
    # Continuing Education CURRENTLY CLOSED" -- program_mismatch, once
    # "continuing education" joined OTHER_PROGRAM_WORDS -- is rejected instead
    # of sitting in the record as apprenticeship evidence.
    #
    # Unlike the 'open' pool, membership here is NOT additionally filtered on
    # ev['asserts'] matching the label. Diagnosis of round 5's LU 567/1340
    # revert: LU 567 emits ONE sentence ("...are closed they will reopen
    # November 2nd, 2026.") twice, once labeled 'closed' and once labeled
    # 'reopening' with stated_effective_date=2026-11-02 on the reopening copy
    # only. _derive_asserts() checks the closed-cue regex before the
    # reopen-cue regex, so BOTH copies' text derives asserts=='closed' -- the
    # word "closed" appears in the sentence and always wins that race. Filtering
    # the reopening pool on asserts=='reopening' therefore drops the one copy
    # carrying the future date, and next_open_date silently disappears or
    # falls back to a weaker source. The fix: a statement's admissibility (do
    # its own words survive the five reject checks) is independent of which
    # status it originates -- gate on label + admissible only, exactly as
    # round 1-4 keyed these two pools before round 5 existed, just now
    # filtered through the same five reject reasons 'open' already gets.
    closed_label_pool = [(s, ev) for s, ev in admitted if "closed" in statement_labels(s)]
    raw_closed_statements = [s for s, ev in closed_label_pool]
    reopening_label_pool = [(s, ev) for s, ev in admitted if "reopening" in statement_labels(s)]
    reopening_statements = [s for s, ev in reopening_label_pool]

    # Round 6, task 2 side effect this module must not let through: gating
    # closed/reopening EVIDENCE also, as an unintended side effect, would
    # weaken rule 1's CONFLICTING check below if that check read the gated
    # pools -- LU 292's "Pre-apprentice hiring is frozen at this time" is
    # correctly gate-rejected as no_application_subject (hiring is a
    # different subject than intake), but that must not silently flip the
    # record from 'conflicting' to 'rolling'. 'conflicting' exists to flag
    # messy raw signals for a human; a closed/reopening LABEL sitting next to
    # a rolling claim is itself worth flagging even when that statement's
    # text doesn't clear the sharper admissibility bar used to decide real
    # open/closed/reopening EVIDENCE. So rule 1 keeps reading the raw,
    # UNGATED label presence (exactly what it read before this round),
    # deliberately more conservative than the gated pools every other rule
    # uses -- this is not a promotion, it is refusing to let task 2
    # accidentally cause one.
    any_raw_closed_or_reopening = any(
        "closed" in statement_labels(s) or "reopening" in statement_labels(s)
        for s in statements
    )

    # ---- round 5, task 2: embedded-date adjudication for 'open' statements.
    # A statement with no usable embedded bound is plain open evidence, same
    # as before. One with a bound/start date is resolved here instead:
    #   future start   -> not open yet; feeds next_open_date (LU 490)
    #   past bound      -> expired, does not count as open (LU 26/1253/607-family)
    #   future bound    -> still open; feeds next_close_date
    #   ambiguous role  -> contributes nothing either way (LU 234)
    # ----
    open_statements = []
    future_open_starts = []       # -> closed_pending / next_open_date
    synthetic_expired_bounds = []  # -> expired_data
    future_open_bound_dates = []   # -> next_close_date
    open_date_precision_note = ""
    embedded_evidence_dates = []   # feeds days_since_evidence/most_recent pools
    for s, ev in raw_open_evidence:
        bounds = [b for b in ev["embedded_bounds"] if b["role"] in ("bound", "start")]
        if not bounds:
            open_statements.append(s)
            continue
        decided = False
        for b in bounds:
            if b["role"] == "start" and b["date"] > today:
                future_open_starts.append(b["date"])
                embedded_evidence_dates.append(b["date"])
                if b["month_inferred"]:
                    open_date_precision_note = "month_inferred"
                decided = True
                break
            if b["role"] == "bound" and b["date"] < today:
                synthetic_expired_bounds.append(b["date"])
                embedded_evidence_dates.append(b["date"])
                decided = True
                break
            if b["role"] == "bound" and b["date"] >= today:
                open_statements.append(s)
                future_open_bound_dates.append(b["date"])
                embedded_evidence_dates.append(b["date"])
                decided = True
                break
            if b["role"] == "start" and b["date"] <= today:
                open_statements.append(s)
                embedded_evidence_dates.append(b["date"])
                decided = True
                break
        if not decided:
            # every bound on this statement was 'ambiguous' (LU 234) -- the
            # statement contributes nothing, demote-safe default.
            pass

    # ---- round 4, tasks 3/4/5 (unchanged): tense- and scope-aware closed-
    # statement processing. Produces the FILTERED closed-statement list every
    # rule below operates on (effective_closed_statements), a pool of
    # candidate next_close_date values, and the corroborated_by_unknown_stmt
    # flag. Round 5 addition: a closed statement that also announces a
    # reopen date (LU 466 "...HAS CLOSED. NEXT ... WILL BEGIN JANUARY 4TH, OF
    # 2027.") must not have that date read as a future_period closure scope
    # -- it is a next_open_date announcement, not a next_close_date one. ----
    effective_closed_statements = []
    future_closed_dates = []
    corroborated_by_unknown_stmt = False
    for s in raw_closed_statements:
        text = s.get("verbatim_text", "")
        # Round 7, task 2: this check must run BEFORE the eff-date branch
        # below, not after. Round 5 fixed LU 466 by putting the
        # reopen-announcement check ahead of closure-scope classification,
        # but the eff-future branch still sat in front of it -- harmless
        # then, because LU 466's closed statement had no structured
        # stated_effective_date of its own. Round 6 task 4's dedup gave
        # LU 567's merged closed/reopening statement a stated_effective_date
        # backfilled from its reopening-labeled duplicate (2026-11-02, in the
        # future), which then hit the eff-future branch FIRST and got read
        # as a future CLOSURE date -- the exact LU 466 bug, reintroduced by
        # a different mechanism (dedup backfill instead of a single
        # statement's own text). Checking the reopen-announcement pattern
        # first, unconditionally, closes that gap regardless of where a
        # future date on the statement came from.
        if REOPEN_ANNOUNCEMENT_IN_CLOSED_RE.search(text):
            # round 5 fix: a reopen announcement embedded in a closure
            # statement is next_open_date information, never next_close_date
            # -- skip closure-scope classification entirely for it (LU 466).
            effective_closed_statements.append(s)
            continue
        eff = _parse_date(s.get("stated_effective_date"))
        if eff and eff > today:
            # task 3: a closed statement whose effective date hasn't arrived
            # yet ANNOUNCES a future closure -- it does not close the local
            # today. LU 112.
            future_closed_dates.append(eff)
            continue
        scope = classify_closure_scope(text, today)
        if scope == "future_period":
            # task 4: confined to a period that hasn't started -- implies
            # currently open. LU 313.
            derived = _derive_future_period_date(text, today)
            if derived:
                future_closed_dates.append(derived)
            continue
        if scope == "past_cohort":
            # task 4/5: names a cohort that's already closed -- says nothing
            # about CURRENT intake on its own. Resolve via any statement
            # (any type, including an 'unknown'-typed one -- task 5:
            # corroborate, never originate) describing the successor intake.
            signal, source = _successor_intake_signal(statements)
            if signal == "accepting":
                if source is not None and source.get("statement_type") == "unknown":
                    corroborated_by_unknown_stmt = True
                continue  # LU 488: resolved -- not closed
            elif signal == "future":
                effective_closed_statements.append(s)  # LU 520: stays closed
                continue
            else:
                continue  # nothing resolves it -- demote, don't count as closed
        effective_closed_statements.append(s)  # unscoped: business as usual

    # ---- all dated evidence, for the recency-ORDERING checks in rules 5/6
    # below (is THIS the newest thing said) -- distinct from
    # days_since_evidence/days_until_next_event (task 1), which must never go
    # negative. Round 5: embedded dates lifted out of open-statement prose
    # join this pool too, since they are just as much "stated" evidence as a
    # structured stated_effective_date field. ----
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
    all_dates.extend(embedded_evidence_dates)
    if page_last_updated:
        all_dates.append(page_last_updated)
    most_recent_any = max(all_dates) if all_dates else None

    days_since_evidence, days_until_next_event = _evidence_recency(
        statements, dated_windows, page_last_updated, today, embedded_evidence_dates,
    )

    recurring_windows = [w for w in windows if w.get("precision") == "recurring"]

    result = _determine_status(
        today, dated_windows, recurring_windows, rolling_statements,
        effective_closed_statements, reopening_statements, open_statements,
        most_recent_any, future_closed_dates,
        future_open_starts, synthetic_expired_bounds, future_open_bound_dates,
        open_date_precision_note,
        rejected_reopening_next_open, rejected_reopening_month_inferred,
        any_raw_closed_or_reopening,
    )
    # Round 4, task 1: audited every comparison against days_since_evidence in
    # the codebase -- _cap_confidence below is the only one, and its `is None`
    # branch is checked first (before any `>` comparison), so it already
    # behaves correctly now that this can genuinely be None with future
    # evidence present (LU 112) rather than only when there's no evidence at all.
    # Round 5, task 3 (LU 400/701): a bounded absolute window with an
    # explicit FUTURE close_date is self-evidently current right now --
    # capping its confidence off how long ago it OPENED would punish exactly
    # the windows that are most clearly still running. _determine_status sets
    # bounded_window_current for that one branch; the age cap is skipped
    # entirely there rather than reapplied against a different basis, since
    # a window that hasn't closed yet has no meaningful "staleness."
    if not result.get("bounded_window_current"):
        result["status_confidence"] = _cap_confidence(
            result["status_confidence"], days_since_evidence, days_until_next_event,
        )
    result["days_since_evidence"] = days_since_evidence
    result["days_until_next_event"] = days_until_next_event
    result["corroborated_by_unknown_stmt"] = corroborated_by_unknown_stmt
    result["intake_pattern"] = result["intake_pattern"] if result["computed_status"] == "rolling" else ""
    result["admitted_statement_count"] = admitted_statement_count
    result["rejected_statement_count"] = rejected_statement_count
    result["embedded_date_conflict"] = embedded_date_conflict
    result.pop("bounded_window_current", None)
    # Round 7, task 2: next_open_date and next_close_date must never be the
    # same date -- a record can't simultaneously open and close on the same
    # day, and the one real case of this (LU 567: a window's open-ended
    # open_date and a reopen-announcement date both landing on 2026-11-02)
    # was always a bug, not a coincidence worth allowing for. This is a
    # canary, not a fix -- if it ever fires, some new code path is feeding an
    # open_date or a reopen announcement into next_close_date again.
    assert not (result["next_open_date"] and result["next_open_date"] == result["next_close_date"]), (
        f"next_open_date == next_close_date == {result['next_open_date']!r} -- "
        "an open_date or reopen announcement is being read as a close bound"
    )
    return result


def _determine_status(today, dated_windows, recurring_windows, rolling_statements,
                       closed_statements, reopening_statements, open_statements,
                       most_recent, future_closed_dates,
                       future_open_starts=None, synthetic_expired_bounds=None,
                       future_open_bound_dates=None, open_date_precision_note="",
                       rejected_reopening_next_open=None,
                       rejected_reopening_month_inferred=False,
                       any_raw_closed_or_reopening=False):
    """Returns a dict: computed_status, status_confidence, intake_pattern,
    next_open_date / next_close_date (ISO string or ''), window_precision_note
    ('' or 'month_boundary_inferred' or 'month_inferred'), inferred_window_status
    (bool -- True if the status came from round-3 recurring-window resolution
    rather than a stated date). status_confidence here is BEFORE the caller
    applies the evidence-age cap.

    rolling_statements has ALREADY passed the round-2 timing gate.
    closed_statements has ALREADY passed round-4's tense/scope filtering in
    compute_status() -- it is the "counts as really closed right now" set,
    not the raw extraction. future_closed_dates feeds next_close_date, which
    is attached to every result regardless of which rule wins (LU 313's
    closure hasn't started yet but is still worth surfacing even though the
    record otherwise lands on 'unknown').

    Round 5, task 2 additions (all already resolved by admit_statement's
    embedded-date adjudication in compute_status() -- this function just
    consumes the resulting pools):
      future_open_starts: dates an 'open' statement's own text says intake
        does not begin until (LU 490) -- next_open_date candidates.
      synthetic_expired_bounds: dates an 'open' statement's own deadline has
        already passed (LU 26/1253/607-family) -- expired_data candidates.
      future_open_bound_dates: dates an 'open' statement's own deadline is
        still ahead -- next_close_date candidates, same treatment as a
        closed statement's future_closed_dates.
      open_date_precision_note: 'month_inferred' when the deciding
        future_open_starts date had no day-of-month in the source text.
    """
    future_open_starts = future_open_starts or []
    synthetic_expired_bounds = synthetic_expired_bounds or []
    future_open_bound_dates = future_open_bound_dates or []

    next_close_date = min(future_closed_dates + future_open_bound_dates) \
        if (future_closed_dates or future_open_bound_dates) else None

    def result(status, confidence, intake_pattern="", next_open_date=None,
               window_precision_note="", inferred_window_status=False,
               bounded_window_current=False):
        return {
            "computed_status": status,
            "status_confidence": confidence,
            "intake_pattern": intake_pattern,
            "next_open_date": next_open_date.isoformat() if next_open_date else "",
            "next_close_date": next_close_date.isoformat() if next_close_date else "",
            "window_precision_note": window_precision_note,
            "inferred_window_status": inferred_window_status,
            "bounded_window_current": bounded_window_current,
        }

    # Round 7, task 1: resolved once, up front, and reused at every call site
    # that needs to know whether a recurring window currently contains
    # TODAY -- the round-6 task-1 override below (rule 4) and the round-3
    # recurring-window resolution rule (5.5) both need this, and computing
    # it in exactly one place is what keeps them from drifting apart again.
    recur = _resolve_recurring_windows(recurring_windows, today)

    # 1. CONFLICTING -- a rolling claim coexists with a closed/reopening claim.
    # Do not try to guess which one is current from text; surface it for a human.
    #
    # Round 7, task 4: documenting the round-6 compromise this condition
    # embeds, per Andrew's request -- this is deliberate, not an oversight.
    #
    # WHAT: the OR'd-in any_raw_closed_or_reopening reads every statement's
    # RAW statement_type label, ungated -- unlike closed_statements/
    # reopening_statements (the two params before it), which are the
    # admissibility-gated, scope-filtered pools every other rule in this
    # function reads. So a closed/reopening-LABELED statement can trigger
    # 'conflicting' here even when admit_statement would reject its own text
    # as insufficient evidence of actual closure.
    #
    # WHY: gating this condition on the same admitted pools as everything
    # else would make 'conflicting' inherit whatever the closed/reopening
    # gate rejects -- and one thing it correctly rejects is text that isn't
    # about intake at all (no_application_subject). Removing that statement
    # from consideration here doesn't just stop it from being closure
    # EVIDENCE; with nothing else contradicting the rolling claim, the
    # record falls through to rule 1b and comes out 'rolling' -- a promotion
    # out of a caution status, which this round's demote-only constraint (and
    # round 6's, before it) does not permit outside the one authorized
    # exception (LU 130, round 6 task 3). So rule 1 deliberately stays on the
    # raw, ungated label -- more conservative than every rule below it, on
    # purpose -- to keep that promotion from happening as an unintended side
    # effect of sharpening what counts as real closure/reopening evidence.
    #
    # WHICH LOCAL: LU 292 Minneapolis. Its "Pre-apprentice hiring is frozen
    # at this time" is labeled 'closed' but is about HIRING, a different
    # subject than application INTAKE -- admit_statement correctly rejects it
    # (no_application_subject). Without this OR clause, LU 292 flips from
    # 'conflicting'/low to 'rolling'/medium the moment that statement is
    # gated out; regression-guarded in
    # TestRound6DatedWindowsAndGating.test_lu292_minneapolis_conflicting_not_promoted_to_rolling.
    #
    # WHAT WOULD REMOVE THIS: 'conflicting' would need to become something
    # other than a single low-confidence catch-all before this distinction
    # could safely collapse -- e.g. a way to flag "raw signals disagree, but
    # the disagreement doesn't survive the gate" as its own, lower-severity
    # signal (worth a human glance, not full 'conflicting' treatment) rather
    # than either merging it into 'rolling' (the promotion this exists to
    # block) or leaving it indistinguishable from a real closed/rolling
    # contradiction (today's behavior). That is a status-taxonomy change, out
    # of scope for a demote-only round.
    if rolling_statements and (closed_statements or reopening_statements or any_raw_closed_or_reopening):
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

    # 2. OPEN -- today inside a dated (absolute) window. Round 4, task 6: an
    # open-ended window (open_date, no close_date) decays -- see the module
    # comment above compute_status for the threshold reasoning. A window
    # with both dates is a bounded, explicit claim and does not decay.
    for w in dated_windows:
        od = _parse_date(w.get("open_date"))
        cd = _parse_date(w.get("close_date"))
        if not od or od > today:
            continue
        if cd is not None:
            if today <= cd:
                # round 5, task 3 (LU 400/701): bounded window with an
                # explicit future close_date is self-evidently current --
                # tell the caller not to cap confidence off open_date age.
                return result("open", "high", bounded_window_current=True)
            continue
        age = (today - od).days
        if age <= 60:
            return result("open", "high")
        if age <= 180:
            return result("open", "medium")
        # else: past 180 days with nobody having closed or updated it --
        # falls through to the decayed-expired check right below, which
        # takes priority over every later rule (an authoritative, specific
        # signal, not a vague one).

    decayed_expired = any(
        _parse_date(w.get("open_date")) and _parse_date(w.get("open_date")) <= today
        and not _parse_date(w.get("close_date"))
        and (today - _parse_date(w.get("open_date"))).days > 180
        for w in dated_windows
    )
    if decayed_expired:
        return result("expired_data", "low")

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

    # 3b. CLOSED_PENDING -- round 5, task 2: an 'open' statement whose own
    # text says intake doesn't begin until a future date (LU 490). Weaker
    # provenance than a structured window/reopening date (rule 3, prose
    # not a stated field) so capped at medium, never high -- same treatment
    # as every other prose-inferred result in this module.
    if future_open_starts:
        note = "month_inferred" if open_date_precision_note else ""
        return result("closed_pending", "medium", next_open_date=min(future_open_starts),
                       window_precision_note=note)

    # 4. OPEN -- round 4, task 2: a prose 'open' statement, with no
    # contradicting present-tense closed statement. Confidence medium, never
    # high -- a prose claim is weaker than a dated window. Deliberately
    # placed AFTER closed_pending (rule 3) rather than the slot suggested in
    # the round-4 task prompt (before closed_pending): a dated future
    # window/reopening is a specific, falsifiable claim, and a vague
    # "Applications Are Currently Open" sentence must not outrank it -- that
    # would be the exact overconfidence bug this round exists to fix, just
    # relocated. No fixture in this round combines the two either way, so
    # this is a demote-safety judgment call, not something a test forces.
    if open_statements and not closed_statements:
        # Round 6, task 1: dated evidence outranks undated prose. By this
        # point every dated_windows entry still in play has EITHER been
        # matched by rule 2 (currently/recently open -- already returned) or
        # has a close_date that has passed with nobody stating otherwise --
        # an open-ended window without a close_date that hasn't decayed past
        # 180 days is also already caught by rule 2's "open" branch, and one
        # that HAS decayed is already caught by the decayed_expired branch
        # right after rule 2. So "every dated_windows entry has a past
        # close_date" is the only shape that can still reach here, and it
        # means every ABSOLUTE dated window on this record has definitively
        # closed.
        #
        # Round 7, task 1: "every dated window has closed" was spec'd (and
        # coded) as absolute windows only. LU 613 Atlanta has an expired
        # absolute window AND a recurring window (August 1-31) that TODAY
        # falls inside -- the recurring window is just as much dated,
        # resolvable evidence as an absolute one, and here it says open. If
        # recur["open_now"] is True, this rule must not fire at all --
        # falling through (no return here) lets control reach rule 5.5 below,
        # which resolves the record via the SAME _resolve_recurring_windows()
        # call already made above and returns open/medium with
        # inferred_window_status=True, the correct provenance for a
        # pattern-inferred result. LU 490 Dover and LU 12 Pueblo are
        # unaffected: both are already resolved by an earlier-firing rule
        # (3b's future_open_starts for LU 490, 1b's ROLLING for LU 12) and
        # never reach this branch at all.
        if not recur["open_now"]:
            if dated_windows and all(
                _parse_date(w.get("close_date")) and _parse_date(w.get("close_date")) < today
                for w in dated_windows
            ):
                return result("expired_data", "medium")
            return result("open", "medium")

    # 5. EXPECTED_OPEN -- reopening date has passed and is the most recent evidence
    past_reopenings = [
        s for s in reopening_statements
        if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) <= today
    ]
    if past_reopenings:
        most_recent_reopen = max(_parse_date(s["stated_effective_date"]) for s in past_reopenings)
        if most_recent is None or most_recent == most_recent_reopen:
            return result("expected_open", "medium")

    # 5.5 (round 3, task 3) -- RECURRING WINDOW RESOLUTION. Runs after every
    # rule based on a stated/absolute date (2, 3, 4, 5) and before the
    # fallbacks that assume no further evidence exists (6, 7, 8). Inferred
    # from a pattern, not a stated date -- always capped at medium, never high.
    # `recur` was already computed once, up front (round 7, task 1) -- reused
    # here rather than recomputed.
    if recur["resolved"]:
        note = "month_boundary_inferred" if recur["inferred"] else ""
        if recur["open_now"]:
            return result("open", "medium", next_open_date=None,
                           window_precision_note=note, inferred_window_status=True)
        else:
            return result("closed_pending", "medium", next_open_date=recur["next_open_date"],
                           window_precision_note=note, inferred_window_status=True)

    # 6. EXPIRED_DATA -- most recent dated window's close has passed, nothing
    # newer. Round 5, task 2: an 'open' statement whose own deadline has
    # passed (LU 26/1253/607-family) joins the same pool -- its bound is just
    # as much a "close" as a window's stated close_date.
    past_close_dates = [
        _parse_date(w.get("close_date")) for w in dated_windows
        if _parse_date(w.get("close_date")) and _parse_date(w.get("close_date")) < today
    ]
    past_close_dates += synthetic_expired_bounds
    if past_close_dates:
        most_recent_close = max(past_close_dates)
        if most_recent is None or most_recent == most_recent_close:
            return result("expired_data", "medium")

    # 7. CLOSED -- explicit closure statement, no reopen date/window anywhere.
    # Round 6, task 3: next_open_date, when available, comes from a
    # reopening-labeled statement that was REJECTED by the admissibility gate
    # (that rejection is why this rule was even reachable -- see the
    # compute_status() comment on rejected_reopening_next_open) rather than
    # from admitted reopening evidence, which would have taken rule 3 instead.
    if closed_statements and not reopening_statements and not dated_windows:
        note = "month_inferred" if rejected_reopening_month_inferred else ""
        return result("closed", "high", next_open_date=rejected_reopening_next_open,
                       window_precision_note=note)

    # 8. UNKNOWN
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


class TestRound4EvidenceRecency(unittest.TestCase):
    """Task 1: days_since_evidence must never go negative; days_until_next_event
    is the new field for future-dated evidence."""
    TODAY = datetime.date(2026, 8, 10)

    def test_only_future_dates_yields_none_and_positive_until(self):
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "We will close on October 1, 2026.",
                "statement_type": "closed", "stated_effective_date": "2026-10-01",
                "source_url": "https://example.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertIsNone(result["days_since_evidence"])
        self.assertEqual(result["days_until_next_event"], 52)

    def test_page_last_updated_ignored_when_stated_dates_exist(self):
        # LU 112's exact shape: page_last_updated is a real past date, but
        # every stated date on the record is in the future -- the page
        # timestamp must not quietly fill in a days_since_evidence value the
        # specific claims don't support.
        record = {
            "windows": [],
            "status_statements": [{
                "verbatim_text": "Closing October 1, 2026.",
                "statement_type": "closed", "stated_effective_date": "2026-10-01",
                "source_url": "https://example.org/",
            }],
            "page_last_updated": "2026-07-08",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertIsNone(result["days_since_evidence"])

    def test_page_last_updated_used_as_fallback_when_no_stated_dates(self):
        record = {"windows": [], "status_statements": [], "page_last_updated": "2026-07-08"}
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["days_since_evidence"], 33)
        self.assertIsNone(result["days_until_next_event"])


class TestClassifyClosureScope(unittest.TestCase):
    """Task 4. Real verbatim_text pulled from extraction_v2.csv where noted;
    synthetic examples are clearly-realistic IBEW-apprenticeship-page phrasing
    used only to round out category coverage to >=5, not tied to a specific
    local's test assertions."""
    TODAY = datetime.date(2026, 8, 10)

    def test_future_period(self):
        cases = [
            "No applications will be accepted in September 2026.",  # LU 313, real
            "The JETC will not be accepting applications in the month of September 2026.",  # LU 176, real
            "Applications will not be reopened until March 2027.",
            "The apprenticeship program will be closed for the month of December 2026.",
            "We will not accept new applications during October 2026.",
        ]
        for text in cases:
            self.assertEqual(classify_closure_scope(text, self.TODAY), "future_period", text)

    def test_past_cohort(self):
        cases = [
            "SELECTION OF APPLICANTS FOR CLASSES BEGINNING SEPTEMBER OF 2026 HAS CLOSED.",  # LU 488, real
            "The Deadline to Submit an Application for September 2026 Classes has passed.",  # LU 520, real (trimmed)
            "Selection of candidates for the Spring 2026 class has closed.",
            "The application deadline for the 2026 cohort has passed.",
            "Enrollment for the September 2026 term has closed.",
        ]
        for text in cases:
            self.assertEqual(classify_closure_scope(text, self.TODAY), "past_cohort", text)

    def test_unscoped_including_traps(self):
        cases = [
            # LU 48: named non-inside programs closed too, but Inside is ALSO
            # named -- must not read as scoped to Limited Energy/Residential.
            "Inside Program – Closed\n\nLimited Energy Program – Closed\n\nResidential Program – Closed",
            # LU 48: "until further notice" is duration, not scope.
            "The Training Center will remain closed for all applications until further notice.",
            # LU 46: "temporarily" is duration, not scope.
            "As of May 1, 2026, Puget Sound Electrical Apprenticeship has temporarily stopped accepting new applications.",
            # LU 11: a past window-closed LOG, not a scoped closure.
            "January 5th, 2026 (APPLICATION WINDOW CLOSED)",
            # LU 728: plain closure with a past date.
            "As of March 9, 2026, online applications are closed.",
            # explicit "indefinitely" trap
            "Applications are closed indefinitely.",
        ]
        for text in cases:
            self.assertEqual(classify_closure_scope(text, self.TODAY), "unscoped", text)


class TestRound4NamedLocals(unittest.TestCase):
    """Task 7. Fixtures built verbatim from out/extraction_v2.csv's
    windows_json/status_statements_json for the six locals the round-4 spec
    is built around. TODAY held at 2026-08-10 throughout."""
    TODAY = datetime.date(2026, 8, 10)

    def test_lu112_open_medium_next_close_date(self):
        record = {
            "windows": [
                {"precision": "absolute", "open_date": "", "close_date": "2026-10-01",
                 "open_month": None, "open_day": None, "close_month": 10, "close_day": 1,
                 "is_recurring_annual": False, "relative_description": "",
                 "evidence_quote": "APPLICATIONS ARE CLOSING OCTOBER 1ST, 2026 - DECEMBER 31, 2026",
                 "source_url": "https://www.jatc112.org/"},
                {"precision": "relative", "open_date": "", "close_date": "",
                 "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                 "is_recurring_annual": False, "relative_description": "APPLICATIONS WILL BE REOPEN IN 2027",
                 "evidence_quote": "APPLICATIONS WILL BE REOPEN IN 2027",
                 "source_url": "https://www.jatc112.org/"},
            ],
            "status_statements": [
                {"verbatim_text": "Applications Are Currently Open", "statement_type": "open",
                 "stated_effective_date": None, "source_url": "https://www.jatc112.org/"},
                {"verbatim_text": "applications are closing October 1, 2026 and will be closed through "
                                   "the remaining of 2026 but will open again in 2027",
                 "statement_type": "closed", "stated_effective_date": "2026-10-01",
                 "source_url": "https://www.jatc112.org/"},
                {"verbatim_text": "After October 1st, 2026 we will only be accepting re-interview "
                                   "applications and applications for 4000 hours qualifier.",
                 "statement_type": "closed", "stated_effective_date": "2026-10-01",
                 "source_url": "https://www.jatc112.org/"},
                {"verbatim_text": "APPLICATIONS WILL BE REOPEN IN 2027.", "statement_type": "reopening",
                 "stated_effective_date": None, "source_url": "https://www.jatc112.org/"},
                {"verbatim_text": "Applications are AVAILABLE as needed throughout the year. Please "
                                   "check our website to get information about our next application window.",
                 "statement_type": "unknown", "stated_effective_date": None,
                 "source_url": "https://www.jatc112.org/"},
            ],
            "page_last_updated": "2026-07-08",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "medium")
        self.assertEqual(result["next_close_date"], "2026-10-01")
        self.assertIsNone(result["days_since_evidence"])
        self.assertEqual(result["days_until_next_event"], 52)

    def test_lu728_open_high_today_decays_to_expired_at_day200(self):
        record = {
            "windows": [{
                "precision": "absolute", "open_date": "2026-07-01", "close_date": "",
                "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                "is_recurring_annual": False, "relative_description": "",
                "evidence_quote": "We will reopen the applications on July 1, 2026.",
                "source_url": "https://www.ibew728.org/",
            }],
            "status_statements": [
                {"verbatim_text": "As of March 9, 2026, online applications are closed.",
                 "statement_type": "closed", "stated_effective_date": "2026-03-09",
                 "source_url": "https://www.ibew728.org/"},
                {"verbatim_text": "We will reopen the applications on July 1, 2026.",
                 "statement_type": "reopening", "stated_effective_date": "2026-07-01",
                 "source_url": "https://www.ibew728.org/"},
            ],
            "page_last_updated": "2026-03-19",
        }
        today_result = compute_status(record, today=self.TODAY)
        self.assertEqual(today_result["computed_status"], "open")
        self.assertEqual(today_result["status_confidence"], "high")

        day200 = datetime.date(2026, 7, 1) + datetime.timedelta(days=200)
        later_result = compute_status(record, today=day200)
        self.assertEqual(later_result["computed_status"], "expired_data")
        self.assertEqual(later_result["status_confidence"], "low")

    def test_lu313_future_period_not_closed(self):
        record = {
            "windows": [{
                "precision": "recurring", "open_date": "", "close_date": "",
                "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                "is_recurring_annual": True,
                "relative_description": "first Wednesday of every month, unless otherwise noted below",
                "evidence_quote": "Applications are on the first Wednesday of every month, unless otherwise noted below.",
                "source_url": "https://www.ibew313.org/",
            }],
            "status_statements": [{
                "verbatim_text": "No applications will be accepted in September 2026.",
                "statement_type": "closed", "stated_effective_date": None,
                "source_url": "https://www.ibew313.org/",
            }],
            "page_last_updated": "2026-07-23",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertNotEqual(result["computed_status"], "closed")
        self.assertEqual(result["next_close_date"], "2026-09-01")

    def test_lu488_past_cohort_resolved_by_unknown_stmt_not_closed(self):
        record = {
            "windows": [{
                "precision": "none", "open_date": "", "close_date": "",
                "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                "is_recurring_annual": False, "relative_description": "",
                "evidence_quote": "Applications are available Monday-Friday from 8 a.m. through 11 a.m.",
                "source_url": "https://www.ibewlocal488.org/content/apprenticeship-opportunities",
            }],
            "status_statements": [
                {"verbatim_text": "SELECTION OF APPLICANTS FOR CLASSES BEGINNING SEPTEMBER OF 2026 HAS CLOSED.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://www.ibewlocal488.org/content/apprenticeship-opportunities"},
                {"verbatim_text": "APPLICATIONS RECEIVED WILL BE FOR CONSIDERATION FOR CLASSES BEGINNING SEPTEMBER 2027.",
                 "statement_type": "unknown", "stated_effective_date": None,
                 "source_url": "https://www.ibewlocal488.org/content/apprenticeship-opportunities"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertNotEqual(result["computed_status"], "closed")
        self.assertTrue(result["corroborated_by_unknown_stmt"])

    def test_lu150_unchanged_regression(self):
        record = {
            "windows": [
                {"precision": "absolute", "open_date": "", "close_date": "2026-01-30",
                 "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                 "is_recurring_annual": False, "relative_description": "",
                 "evidence_quote": "documents must be uploaded...NO LATER THAN 4:00pm on 1/30/2026",
                 "source_url": "https://lakecountyjatc.org/howtoapply/"},
                {"precision": "absolute", "open_date": "2026-10-01", "close_date": "",
                 "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                 "is_recurring_annual": False, "relative_description": "",
                 "evidence_quote": "Applications will reopen on October 1, 2026",
                 "source_url": "https://lakecountyjatc.org/howtoapply/"},
            ],
            "status_statements": [
                {"verbatim_text": "Applications for the 2026 Program are now CLOSED",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://lakecountyjatc.org/howtoapply/"},
                {"verbatim_text": "Applications will reopen on October 1, 2026",
                 "statement_type": "reopening", "stated_effective_date": "2026-10-01",
                 "source_url": "https://lakecountyjatc.org/howtoapply/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["status_confidence"], "high")
        self.assertEqual(result["next_open_date"], "2026-10-01")

    def test_lu520_unchanged_regression(self):
        record = {
            "windows": [{
                "precision": "absolute", "open_date": "", "close_date": "2026-06-21",
                "open_month": None, "open_day": None, "close_month": None, "close_day": None,
                "is_recurring_annual": False, "relative_description": "",
                "evidence_quote": "last day to submit a complete and accurate application is on June 21, 2026",
                "source_url": "https://austineta.org/news/",
            }],
            "status_statements": [{
                "verbatim_text": "The Deadline to Submit an Application for September 2026 Classes has "
                                   "passed...when we begin accepting applications for the next term we "
                                   "will announce it here!",
                "statement_type": "closed", "stated_effective_date": None,
                "source_url": "https://austineta.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed")
        self.assertEqual(result["status_confidence"], "medium")


class TestRound5AdmissibilityGate(unittest.TestCase):
    """Round 5. Every verbatim_text below is pulled verbatim from
    out/extraction_v2.csv for the named local -- see PROMPT_status_round5.md,
    "The failing records. These are the spec." TODAY held at 2026-08-10
    throughout, per round 4's convention."""
    TODAY = datetime.date(2026, 8, 10)

    def _record(self, statements, windows=None, page_last_updated=None):
        return {
            "windows": windows or [],
            "status_statements": statements,
            "page_last_updated": page_last_updated,
        }

    def _open_stmt(self, text, source="https://example.org/"):
        return {"verbatim_text": text, "statement_type": "open",
                "stated_effective_date": None, "source_url": source}

    # -- the deadline-family (LU 26, 1253, 607) -----------------------------

    def test_lu26_washington_dc_expired_data_with_conflict(self):
        record = self._record([self._open_stmt(
            "Applications currently being accepted are for the Class of 2030. "
            "The deadline to apply is March 31, 2025.",
            "https://ibewlocal26.org/join-as-individual/training/",
        )], windows=[{
            "precision": "absolute", "open_date": "", "close_date": "2025-03-31",
            "open_month": None, "open_day": None, "close_month": None, "close_day": None,
            "is_recurring_annual": False, "relative_description": "",
            "evidence_quote": "The deadline to apply is March 31, 2025.",
            "source_url": "https://ibewlocal26.org/join-as-individual/training/",
        }])
        result = compute_status(record, today=self.TODAY)
        self.assertNotEqual(result["computed_status"], "open")
        self.assertEqual(result["computed_status"], "expired_data")
        self.assertTrue(result["embedded_date_conflict"])

    def test_lu1253_augusta_not_open(self):
        record = self._record([
            self._open_stmt(
                "FALL 2026 APPRENTICESHIP OPPORTUNITY: Applications are due March 31, 2026.",
                "https://www.ibew1253.org/",
            ),
            {"verbatim_text": "All applications and testing completed after these dates will be "
                               "considered for the fall of 2027 apprenticeship",
             "statement_type": "unknown", "stated_effective_date": None,
             "source_url": "https://www.ibew1253.org/"},
        ])
        result = compute_status(record, today=self.TODAY)
        self.assertNotEqual(result["computed_status"], "open")

    def test_lu607_shamokin_not_open(self):
        record = self._record([self._open_stmt(
            "Apply in person or online until April 10th, 2026, at 25 South 5th St, "
            "Shamokin, PA or down below.",
            "https://ibew607.com/apprenticeship",
        )])
        result = compute_status(record, today=self.TODAY)
        self.assertNotEqual(result["computed_status"], "open")

    def test_lu490_dover_closed_pending_month_inferred(self):
        record = self._record([self._open_stmt(
            "We are accepting applications for the 2027-2028 school year starting "
            "August of 2027.",
            "https://ibew490.org/apprenticeship/",
        )])
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["next_open_date"], "2027-08-01")
        self.assertEqual(result["window_precision_note"], "month_inferred")

    def test_lu234_castroville_unknown(self):
        record = self._record([self._open_stmt(
            "Accepting applications by mail only. To be eligible for the next aptitude "
            "test in February 2027, applications must be received before or postmarked "
            "no later than Friday, December 18, 2026.",
            "https://www.tricountyjatc.org/",
        )])
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    # -- the method-only family (LU 494, 1205, 16) ---------------------------

    def test_lu494_milwaukee_method_only_unknown(self):
        record = self._record([self._open_stmt(
            "If you meet the minimum qualifications you may apply by following this "
            "link CLICK HERE",
            "https://www.ibew494.com/",
        )])
        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][0], self.TODAY)
        self.assertEqual(ev["reject_reason"], "method_only")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    def test_lu1205_gainesville_method_only_unknown(self):
        record = self._record([self._open_stmt(
            "Currently, applications can be obtained in person at Gainesville "
            "Electrical Joint Apprenticeship and Training Committee D/B/A, Electrical "
            "Training Alliance of Gainesville or by clicking on the link below to "
            "download and print a copy of the application.",
            "https://www.ibew1205.org/",
        )])
        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][0], self.TODAY)
        self.assertEqual(ev["reject_reason"], "method_only")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    def test_lu16_evansville_method_only_unknown(self):
        record = self._record([self._open_stmt(
            "Online applications for both the inside and residential program are "
            "available. Click on the Apply Online button on the Applicants page.",
            "https://evvjatc.org/applicants/",
        )])
        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][0], self.TODAY)
        self.assertEqual(ev["reject_reason"], "method_only")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    # -- CTA-only, office-hours, program-mismatch ----------------------------

    def test_lu163_wilkes_barre_cta_only_unknown(self):
        record = self._record([self._open_stmt(
            "Start your application to the IBEW Local 163 JATC Apprenticeship Program today!",
            "https://www.ibew163.org/apprenticeship-training/",
        )])
        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][0], self.TODAY)
        self.assertEqual(ev["reject_reason"], "cta_only")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    def test_lu601_champaign_urbana_office_hours_unknown(self):
        record = self._record([self._open_stmt(
            "Summer Hours for applications: Wednesdays from 12:30 pm - 3:30 pm",
            "https://www.ibew601.org/apprenticeshipopportunitydocument/",
        )])
        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][0], self.TODAY)
        self.assertEqual(ev["reject_reason"], "office_hours")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "unknown")

    def test_lu229_york_program_mismatch_not_open(self):
        cw_stmt = self._open_stmt(
            "⚡ Now Accepting Applications – Construction Wireman / "
            "Construction Electrician Program",
            "https://www.ibew229.org/content/membership-application",
        )
        from statement_evidence import admit_statement
        ev = admit_statement(cw_stmt, self.TODAY)
        self.assertEqual(ev["reject_reason"], "program_mismatch")

        record = self._record([
            self._open_stmt(
                "To make application for the IBEW Inside Wireman Apprenticeship you "
                "must apply online.",
                "https://www.ibew229.org/",
            ),
            cw_stmt,
        ])
        result = compute_status(record, today=self.TODAY)
        self.assertNotEqual(result["computed_status"], "open")

    def test_lu153_south_bend_survives_cta_check(self):
        # "Applications Are OPEN Apply NOW!!!" carries a state claim
        # (OPEN_STATE_CUE_RE) and must NOT be rejected as cta_only.
        record = self._record([self._open_stmt(
            "Applications Are OPEN Apply NOW!!!",
            "https://www.jatc153.com/?zone=/unionactive/view_page.cfm&page=Apprentice20Resources",
        )])
        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][0], self.TODAY)
        self.assertTrue(ev["admissible"])
        self.assertEqual(ev["asserts"], "open")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")

    def test_lu48_portland_program_rule_does_not_fire_when_inside_named(self):
        # Inside is named ALONGSIDE the other programs -- must stay admissible
        # and the local must stay closed (round 4 regression).
        record = self._record([
            {"verbatim_text": "Inside Program – Closed\n\nLimited Energy Program – "
                               "Closed\n\nResidential Program – Closed",
             "statement_type": "closed", "stated_effective_date": None,
             "source_url": "https://nietc.org/applicants/preparing-to-apply/current-application-openings/"},
            {"verbatim_text": "The Training Center will remain closed for all applications "
                               "until further notice. Any updates will be posted on this page.",
             "statement_type": "closed", "stated_effective_date": None,
             "source_url": "https://nietc.org/applicants/preparing-to-apply/current-application-openings/"},
            {"verbatim_text": "We are not accepting new requests for reinterviews at this "
                               "time due to the current work slowdown and pause on new "
                               "apprentice classes.",
             "statement_type": "closed", "stated_effective_date": None,
             "source_url": "https://nietc.org/applicants/preparing-to-apply/current-application-openings/"},
        ], page_last_updated="2026-05-01")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed")
        self.assertEqual(result["status_confidence"], "high")

    # -- task 3: LU 400/701 confidence restored; LU 466 assignment fix -------

    def test_lu400_bounded_window_future_close_stays_high(self):
        record = self._record([], windows=[{
            "precision": "absolute", "open_date": "2026-01-01", "close_date": "2026-12-31",
            "open_month": None, "open_day": None, "close_month": None, "close_day": None,
            "is_recurring_annual": False, "relative_description": "",
            "evidence_quote": "Application Period: January 1, 2026 through December 31, 2026",
            "source_url": "https://www.ibew400.org/jatc/apprenticeship/",
        }])
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "high")

    def test_lu701_dupage_bounded_window_future_close_stays_high(self):
        record = self._record([self._open_stmt(
            "Applications moving online starting 10/1/25. Click Here to Apply",
            "https://dupagejatc.org/",
        )], windows=[{
            "precision": "absolute", "open_date": "2025-10-01", "close_date": "2026-09-30",
            "open_month": None, "open_day": None, "close_month": None, "close_day": None,
            "is_recurring_annual": False, "relative_description": "",
            "evidence_quote": "accepting applications online starting on 10/1/25 through September 30, 2026",
            "source_url": "https://dupagejatc.org/wp-content/uploads/2025/10/Application-Info-2027.pdf",
        }])
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "high")

    def test_lu466_charleston_reopen_date_is_next_open_not_next_close(self):
        record = self._record([{
            "verbatim_text": "2026 APPLICATION PERIOD HAS CLOSED. NEXT APPLICATION PERIOD "
                              "WILL BEGIN JANUARY 4TH, OF 2027. THANK YOU TO ALL THAT HAVE APPLIED.",
            "statement_type": "closed", "stated_effective_date": None,
            "source_url": "https://www.ibew466.org/?zone=/unionactive/view_page.cfm&page=Apprenticeship",
        }], windows=[{
            "precision": "absolute", "open_date": "2027-01-04", "close_date": "",
            "open_month": None, "open_day": None, "close_month": None, "close_day": None,
            "is_recurring_annual": False, "relative_description": "",
            "evidence_quote": "NEXT APPLICATION PERIOD WILL BEGIN JANUARY 4TH, OF 2027.",
            "source_url": "https://www.ibew466.org/?zone=/unionactive/view_page.cfm&page=Apprenticeship",
        }], page_last_updated="2026-04-22")
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["next_open_date"], "2027-01-04")
        self.assertEqual(result["next_close_date"], "")

    # -- regression guards: 14 named locals, unchanged status/confidence ----

    def test_regression_guards_unchanged(self):
        cases = [
            ("LU68 Denver", [self._open_stmt("Applications now open.", "https://djeatc68.com/apply/")],
             "open", "medium"),
            ("LU570 Tucson", [self._open_stmt("We are now accepting Applications online.", "https://www.tucsonjatc.org/")],
             "open", "medium"),
            ("LU38 Cleveland", [self._open_stmt("The JATC is now accepting applications on-line, 24/7.", "https://ibew38.org/jatc/")],
             "open", "medium"),
            ("LU236 Albany", [self._open_stmt("Applications for apprenticeship are now being accepted.", "https://www.tricityjatc.org/")],
             "open", "medium"),
            ("LU112 Kennewick", [self._open_stmt("Applications Are Currently Open", "https://www.jatc112.org/")],
             "open", "medium"),
            ("LU153 South Bend", [self._open_stmt("Applications Are OPEN", "https://www.jatc153.com/index.cfm")],
             "open", "medium"),
            ("LU110 St. Paul", [self._open_stmt(
                "The St. Paul Electrical Joint Apprenticeship and Training Committee (JATC) "
                "is now accepting applications for entry into our comprehensive Apprenticeship "
                "Program.", "https://www.jatc110.org/")], "open", "medium"),
            ("LU558 Sheffield", [self._open_stmt(
                "The North Alabama Electrical Training Alliance is now accepting applications "
                "for our four-year construction apprenticeship training program.",
                "https://naeta.org/")], "open", "medium"),
            ("LU456 New Brunswick", [self._open_stmt(
                "Applications are Currently being Accepted Today, CLICK HERE.",
                "https://ibew456.org/training.aspx")], "open", "medium"),
            ("LU34 Peoria", [self._open_stmt("Now accepting online applications", "https://peoriajatc.com/")],
             "open", "medium"),
            ("LU575 Portsmouth", [self._open_stmt(
                "Accepting Applications for an Electrical Apprenticeship",
                "https://www.ibew575.org/application_information/")], "open", "medium"),
            ("LU673 Painesville", [self._open_stmt(
                "This Joint Apprenticeship and Training Committee (JATC) is accepting "
                "applications for apprenticeship.", "https://ibew673.org/")], "open", "medium"),
            ("LU270 Oak Ridge", [self._open_stmt("now accepting applications", "https://www.orejatc.org/")],
             "open", "medium"),
            ("LU972 Marietta", [self._open_stmt(
                "Marietta Electrical JATC is currently taking applications for Apprentices "
                "to become Inside Wireman.", "https://www.ibew972.com/apprrenticeshiptraining/")],
             "open", "medium"),
        ]
        for name, statements, expected_status, expected_conf in cases:
            record = self._record(statements)
            result = compute_status(record, today=self.TODAY)
            self.assertEqual(result["computed_status"], expected_status, name)
            self.assertEqual(result["status_confidence"], expected_conf, name)


class TestAdmitStatementUnits(unittest.TestCase):
    """Round 5, task 5: >=4 admit_statement fixtures per reject reason, plus
    the date-parser and cohort-vs-bound coverage task 2 asks for."""
    TODAY = datetime.date(2026, 8, 10)

    def _admit(self, text):
        from statement_evidence import admit_statement
        return admit_statement({"verbatim_text": text}, self.TODAY)

    def test_no_application_subject_x4(self):
        for text in [
            "We look forward to seeing you at the union hall.",
            "The apprenticeship provides excellent wages and benefits.",
            "Our office hours are Monday through Friday.",
            "For general questions, please call the main line.",
        ]:
            self.assertFalse(self._admit(text)["admissible"], text)
            self.assertEqual(self._admit(text)["reject_reason"], "no_application_subject", text)

    def test_method_only_x4(self):
        for text in [
            "If you meet the minimum qualifications you may apply by following this link CLICK HERE",
            "Currently, applications can be obtained in person at our office or by clicking the link below.",
            "Online applications for both the inside and residential program are available. Click Apply Online.",
            "To make application for the IBEW Inside Wireman Apprenticeship you must apply online.",
        ]:
            self.assertEqual(self._admit(text)["reject_reason"], "method_only", text)

    def test_cta_only_x4(self):
        for text in [
            "Start your application to the IBEW Local 163 JATC Apprenticeship Program today!",
            "Start the application process to join the IBEW Local 163 JATC apprenticeship program today!",
            "Apply now for the apprenticeship program!",
            "Begin your application for the apprenticeship program now!",
        ]:
            self.assertEqual(self._admit(text)["reject_reason"], "cta_only", text)

    def test_office_hours_x4(self):
        for text in [
            "Summer Hours for applications: Wednesdays from 12:30 pm - 3:30 pm",
            "Applications accepted Monday - Friday 8:00 a.m. - 4:00 p.m.",
            "Application office hours are 9am to 5pm on weekdays.",
            "Applications available Monday through Friday, 8am-4:30pm.",
        ]:
            self.assertEqual(self._admit(text)["reject_reason"], "office_hours", text)

    def test_program_mismatch_x4(self):
        for text in [
            "Now Accepting Applications – Construction Wireman / Construction Electrician Program",
            "We are accepting applications for the Residential Apprenticeship Program.",
            "Applications for the VDV apprenticeship are now open.",
            "Now accepting applications for the Limited Energy program.",
        ]:
            self.assertEqual(self._admit(text)["reject_reason"], "program_mismatch", text)

    def test_date_parser_formats(self):
        from statement_evidence import extract_embedded_dates
        cases = [
            ("The deadline to apply is March 31, 2025.", datetime.date(2025, 3, 31)),
            ("The deadline to apply is March 31st, 2025.", datetime.date(2025, 3, 31)),
            ("Applications due by 3/31/2025.", datetime.date(2025, 3, 31)),
            ("Applications close 2025-03-31.", datetime.date(2025, 3, 31)),
            ("Apply in person or online until April 10th, 2026.", datetime.date(2026, 4, 10)),
        ]
        for text, expected in cases:
            dates = [e["date"] for e in extract_embedded_dates(text)]
            self.assertIn(expected, dates, text)

    def test_date_parser_bare_month_year(self):
        from statement_evidence import extract_embedded_dates
        starting = extract_embedded_dates("starting August of 2027")
        self.assertEqual(starting[0]["date"], datetime.date(2027, 8, 1))
        self.assertEqual(starting[0]["role"], "start")
        self.assertTrue(starting[0]["month_inferred"])

        eligible = extract_embedded_dates("eligible for the next aptitude test in February 2027")
        self.assertEqual(eligible[0]["date"].year, 2027)
        self.assertEqual(eligible[0]["date"].month, 2)

    def test_cohort_reference_not_read_as_bound(self):
        from statement_evidence import extract_embedded_dates
        for text in [
            "Applications currently being accepted are for the Class of 2030.",
            "We are accepting applications for the 2027-2028 school year.",
        ]:
            dates = extract_embedded_dates(text)
            self.assertTrue(dates, text)
            for d in dates:
                self.assertEqual(d["role"], "cohort", text)


class TestRound6DatedWindowsAndGating(unittest.TestCase):
    """Round 6. verbatim_text/windows pulled from out/extraction_v2.csv for
    every named local -- see PROMPT_status_round6.md. TODAY held at
    2026-08-10 throughout, per round 4-5's convention."""
    TODAY = datetime.date(2026, 8, 10)

    # -- task 1: dated windows beat undated prose -----------------------

    def test_lu613_atlanta_expired_data_and_program_mismatch(self):
        # Superseded by round 7, task 1: the recurring window (August 1-31)
        # contains TODAY, so this now correctly resolves 'open', not
        # 'expired_data' -- see TestRound7RecurringWindowsAndCloseDate below
        # for the round-7 fixture and rationale. Kept here (status updated)
        # so this test class still documents the record's full history; the
        # program_mismatch assertion (round 6, task 2) is unaffected by round
        # 7 and still holds.
        record = {
            "windows": [
                {"precision": "absolute", "open_date": "2026-02-01", "close_date": "2026-03-31"},
                {"precision": "recurring", "open_month": 8, "open_day": 1,
                 "close_month": 8, "close_day": 31, "is_recurring_annual": False,
                 "relative_description": "August 1st - August 31st",
                 "evidence_quote": "Apprenticeship Program Applications Now OPEN! August 1st - August 31st",
                 "source_url": "https://6601etc.wordpress.com/"},
            ],
            "status_statements": [
                {"verbatim_text": "Apprenticeship Program Applications Now OPEN!",
                 "statement_type": "open", "stated_effective_date": None,
                 "source_url": "https://6601etc.wordpress.com/"},
                {"verbatim_text": "Journeyman Wireman Continuing Education CURRENTLY CLOSED",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://6601etc.wordpress.com/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")
        self.assertEqual(result["status_confidence"], "medium")
        self.assertTrue(result["inferred_window_status"])

        from statement_evidence import admit_statement
        ev = admit_statement(record["status_statements"][1], self.TODAY)
        self.assertEqual(ev["reject_reason"], "program_mismatch")

    def test_lu538_danville_expired_data(self):
        record = {
            "windows": [
                {"precision": "absolute", "open_date": "2026-03-30", "close_date": "2026-04-03"},
                {"precision": "absolute", "open_date": "2026-04-06", "close_date": "2026-04-10"},
            ],
            "status_statements": [{
                "verbatim_text": "The JATC will be taking applications on the following days in 2026",
                "statement_type": "open", "stated_effective_date": None,
                "source_url": "https://ibew538.org/apprenticeship-cet/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "expired_data")
        self.assertEqual(result["status_confidence"], "medium")

    def test_synthetic_undated_open_with_currently_open_window_stays_open(self):
        # task 1's rule must only fire when EVERY dated window has closed --
        # one still-open window must let the undated prose (and rule 2's
        # window match) stand.
        record = {
            "windows": [{"precision": "absolute", "open_date": "2026-08-01", "close_date": "2026-08-31"}],
            "status_statements": [{
                "verbatim_text": "Applications are currently open.",
                "statement_type": "open", "stated_effective_date": None,
                "source_url": "https://example.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "open")

    # -- task 2: closed/reopening gated, LU 567/1340 date survives ------

    def test_lu567_unchanged_and_duplicate_counted_once(self):
        text = "Applications for IBEW 567 Apprenticeship are closed they will reopen November 2nd, 2026."
        record = {
            "windows": [{"precision": "absolute", "open_date": "2026-11-02", "close_date": ""}],
            "status_statements": [
                {"verbatim_text": text, "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://www.ibew567.com/apprenticeship/"},
                {"verbatim_text": text, "statement_type": "reopening", "stated_effective_date": "2026-11-02",
                 "source_url": "https://www.ibew567.com/apprenticeship/advantages-of-joining/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["status_confidence"], "high")
        self.assertEqual(result["next_open_date"], "2026-11-02")
        self.assertEqual(result["admitted_statement_count"], 1)

    def test_lu1340_newport_news_unchanged(self):
        record = {
            "windows": [
                {"precision": "recurring", "open_month": 12, "open_day": 1,
                 "close_month": 4, "close_day": 30, "is_recurring_annual": True},
                {"precision": "absolute", "open_date": "2026-12-01", "close_date": ""},
            ],
            "status_statements": [{
                "verbatim_text": "THE DEADLINE FOR THE UPCOMING SCHOOL YEAR HAS PASSED, APPLICATIONS FOR "
                                   "THE 2027 SCHOOL YEAR WILL BE AVAILABLE DECEMBER 1, 2026",
                "statement_type": "reopening", "stated_effective_date": "2026-12-01",
                "source_url": "http://hamptonroadsjatc.com/?zone=/unionactive/view_page.cfm&page=Applications",
            }],
            "page_last_updated": "2026-08-10",
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["status_confidence"], "high")
        self.assertEqual(result["next_open_date"], "2026-12-01")

    def test_lu292_minneapolis_conflicting_not_promoted_to_rolling(self):
        # round-6 regression guard: gating "Pre-apprentice hiring is frozen"
        # out of closed-EVIDENCE (it's about hiring, not intake -- correctly
        # rejected no_application_subject) must not also flip the record out
        # of 'conflicting', the one status this round is not allowed to
        # promote out of.
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "Applications are open year-round for the Apprenticeship program, "
                                   "but hiring is completed as needed, typically during late spring "
                                   "and summer months.",
                 "statement_type": "rolling", "stated_effective_date": None,
                 "source_url": "https://mplsjatc.org/"},
                {"verbatim_text": "Pre-apprentice hiring is frozen at this time.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://mplsjatc.org/applicants/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "conflicting")
        self.assertEqual(result["status_confidence"], "low")

    # -- task 3: LU 130 -----------------------------------------------------

    def test_lu130_new_orleans_closed_with_inferred_next_open(self):
        record = {
            "windows": [],
            "status_statements": [
                {"verbatim_text": "APPLICATIONS FOR THE 2026-2027 SCHOOL YEAR ARE NOW CLOSED.",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://ibewlu130.com/apprenticeship/"},
                {"verbatim_text": "Please contact the office in January 2027 for information "
                                   "regarding the 2027-2028 school year.",
                 "statement_type": "reopening", "stated_effective_date": None,
                 "source_url": "https://ibewlu130.com/apprenticeship/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed")
        self.assertEqual(result["next_open_date"], "2027-01-01")
        self.assertEqual(result["window_precision_note"], "month_inferred")

    # -- round 4 guards must stay unchanged ------------------------------

    def test_lu520_austin_unchanged(self):
        record = {
            "windows": [{
                "precision": "absolute", "open_date": "", "close_date": "2026-06-21",
                "source_url": "https://austineta.org/news/",
            }],
            "status_statements": [{
                "verbatim_text": "The Deadline to Submit an Application for September 2026 Classes has "
                                   "passed...when we begin accepting applications for the next term we "
                                   "will announce it here!",
                "statement_type": "closed", "stated_effective_date": None,
                "source_url": "https://austineta.org/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed")
        self.assertEqual(result["status_confidence"], "medium")

    def test_lu150_unchanged(self):
        record = {
            "windows": [
                {"precision": "absolute", "open_date": "", "close_date": "2026-01-30"},
                {"precision": "absolute", "open_date": "2026-10-01", "close_date": ""},
            ],
            "status_statements": [
                {"verbatim_text": "Applications for the 2026 Program are now CLOSED",
                 "statement_type": "closed", "stated_effective_date": None,
                 "source_url": "https://lakecountyjatc.org/howtoapply/"},
                {"verbatim_text": "Applications will reopen on October 1, 2026",
                 "statement_type": "reopening", "stated_effective_date": "2026-10-01",
                 "source_url": "https://lakecountyjatc.org/howtoapply/"},
            ],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "closed_pending")
        self.assertEqual(result["status_confidence"], "high")
        self.assertEqual(result["next_open_date"], "2026-10-01")

    def test_lu26_dc_still_expired_data(self):
        record = {
            "windows": [{
                "precision": "absolute", "open_date": "", "close_date": "2025-03-31",
                "source_url": "https://ibewlocal26.org/join-as-individual/training/",
            }],
            "status_statements": [{
                "verbatim_text": "Applications currently being accepted are for the Class of 2030. "
                                   "The deadline to apply is March 31, 2025.",
                "statement_type": "open", "stated_effective_date": None,
                "source_url": "https://ibewlocal26.org/join-as-individual/training/",
            }],
            "page_last_updated": None,
        }
        result = compute_status(record, today=self.TODAY)
        self.assertEqual(result["computed_status"], "expired_data")

    def test_regression_guards_14_prose_only_open_unchanged(self):
        cases = [
            ("LU68 Denver", "Applications now open.", "https://djeatc68.com/apply/"),
            ("LU570 Tucson", "We are now accepting Applications online.", "https://www.tucsonjatc.org/"),
            ("LU38 Cleveland", "The JATC is now accepting applications on-line, 24/7.", "https://ibew38.org/jatc/"),
            ("LU236 Albany", "Applications for apprenticeship are now being accepted.", "https://www.tricityjatc.org/"),
            ("LU112 Kennewick", "Applications Are Currently Open", "https://www.jatc112.org/"),
            ("LU153 South Bend", "Applications Are OPEN", "https://www.jatc153.com/index.cfm"),
            ("LU110 St. Paul", "The St. Paul Electrical Joint Apprenticeship and Training Committee (JATC) "
                                "is now accepting applications for entry into our comprehensive Apprenticeship "
                                "Program.", "https://www.jatc110.org/"),
            ("LU558 Sheffield", "The North Alabama Electrical Training Alliance is now accepting applications "
                                 "for our four-year construction apprenticeship training program.", "https://naeta.org/"),
            ("LU456 New Brunswick", "Applications are Currently being Accepted Today, CLICK HERE.",
             "https://ibew456.org/training.aspx"),
            ("LU34 Peoria", "Now accepting online applications", "https://peoriajatc.com/"),
            ("LU575 Portsmouth", "Accepting Applications for an Electrical Apprenticeship",
             "https://www.ibew575.org/application_information/"),
            ("LU673 Painesville", "This Joint Apprenticeship and Training Committee (JATC) is accepting "
                                   "applications for apprenticeship.", "https://ibew673.org/"),
            ("LU270 Oak Ridge", "now accepting applications", "https://www.orejatc.org/"),
            ("LU972 Marietta", "Marietta Electrical JATC is currently taking applications for Apprentices "
                                "to become Inside Wireman.", "https://www.ibew972.com/apprrenticeshiptraining/"),
        ]
        for name, text, url in cases:
            record = {
                "windows": [],
                "status_statements": [{
                    "verbatim_text": text, "statement_type": "open",
                    "stated_effective_date": None, "source_url": url,
                }],
                "page_last_updated": None,
            }
            result = compute_status(record, today=self.TODAY)
            self.assertEqual(result["computed_status"], "open", name)
            self.assertEqual(result["status_confidence"], "medium", name)

    # -- task 4: de-duplication -------------------------------------------

    def test_dedupe_statements_merges_and_backfills_date(self):
        from statement_evidence import dedupe_statements
        text = "Applications for IBEW 567 Apprenticeship are closed they will reopen November 2nd, 2026."
        statements = [
            {"verbatim_text": text, "statement_type": "closed", "stated_effective_date": None,
             "source_url": "a"},
            {"verbatim_text": text, "statement_type": "reopening", "stated_effective_date": "2026-11-02",
             "source_url": "b"},
        ]
        deduped, audit = dedupe_statements(statements)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["stated_effective_date"], "2026-11-02")
        self.assertEqual(sorted(deduped[0]["combined_types"]), ["closed", "reopening"])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["duplicate_count"], 2)

    def test_dedupe_statements_normalises_whitespace_and_punctuation(self):
        from statement_evidence import dedupe_statements
        statements = [
            {"verbatim_text": "Applications are OPEN!!", "statement_type": "open",
             "stated_effective_date": None, "source_url": "a"},
            {"verbatim_text": "applications are open", "statement_type": "open",
             "stated_effective_date": None, "source_url": "b"},
        ]
        deduped, audit = dedupe_statements(statements)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(audit[0]["duplicate_count"], 2)

    def test_dedupe_statements_no_duplicates_passthrough(self):
        from statement_evidence import dedupe_statements
        statements = [
            {"verbatim_text": "Applications are open.", "statement_type": "open",
             "stated_effective_date": None, "source_url": "a"},
            {"verbatim_text": "Applications close March 1.", "statement_type": "closed",
             "stated_effective_date": None, "source_url": "b"},
        ]
        deduped, audit = dedupe_statements(statements)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(audit, [])


if __name__ == "__main__":
    unittest.main()
