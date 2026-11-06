"""
Round 5: one admissibility gate every status_statement passes through, no
matter what statement_type label the extractor put on it.

Why this exists: round 2 fixed 'rolling' statements by requiring an
application subject plus temporal language, ignoring method-only text.
Round 4 wired in statement_type == 'open' without an equivalent gate, and the
identical defect reappeared (LU 26, 490, 1253, 607, 234, 494, 1205, 16, 163,
601, 229 -- see PROMPT_status_round5.md). This module is the fix that is
meant to generalize to every statement_type, present and future:
statement_type is an unreliable LLM label, treated here as a hint about
intent, never as evidence about content. `asserts` is derived from
verbatim_text; where the label and `asserts` disagree, the text wins.

admit_statement(stmt, today) -> dict:
    admissible: bool
    reject_reason: str            '' when admissible
    asserts: str                  'open'|'closed'|'rolling'|'reopening'|'none'
    embedded_dates: [date]        every date lifted from verbatim_text
    embedded_bounds: [dict]       internal detail consumed by compute_status;
                                   each entry: {"date": date, "role":
                                   'bound'|'start'|'cohort'|'ambiguous',
                                   "month_inferred": bool}
    tense: str                    'past'|'present'|'future'|'unknown'
    scope: str                    classify_closure_scope() result, '' if n/a
    program: str                  'inside'|'other'|'unspecified'
    embedded_date_conflict: bool  an embedded date contradicts the text's own
                                   claim (e.g. "currently being accepted" with
                                   a bound that has already passed)

Every rejection here is a DEMOTION: an admissible statement can become
inadmissible, an 'open' assertion can fall back to 'none', but nothing here
ever manufactures a positive assertion or upgrades a downstream confidence.
"""
import calendar
import datetime
import re

# Deliberately late/local import target for compute_status.py (see the
# bottom-of-module note there) to avoid a circular import: this module reads
# constants/functions that live in compute_status.py, and compute_status.py
# imports admit_statement from here. As long as compute_status.py finishes
# defining those symbols before it imports this module, the cycle resolves
# fine -- Python module objects are populated incrementally as they execute.
from compute_status import (
    APPLICATION_SUBJECT_WORDS,
    classify_intake,
    classify_closure_scope,
    MONTH_NUM,
    _PAST_FRAMING_RE,
)
from window_rules import _MONTH_NAME_RE

# window_rules._CLOCK_TIME_RE's trailing \b fails on "a.m."/"p.m." (a period
# is a non-word char, so no word boundary exists right after it) -- that bug
# was latent there because is_suspect_window's other reasons (e.g.
# recurring_not_resolvable) happened to catch every existing fixture some
# other way. Statements don't get that safety net, so this module uses its
# own, more forgiving clock-time match instead of importing the flawed one.
_CLOCK_TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Task 1, rule 1: no application subject. Reuses round 2's vocabulary --
# imported above, not duplicated.
# ---------------------------------------------------------------------------


def _has_application_subject(low):
    return any(k in low for k in APPLICATION_SUBJECT_WORDS)


# ---------------------------------------------------------------------------
# Task 1, rule 2: method-only. Describes HOW to apply, asserts nothing about
# WHETHER intake is happening. An explicit state/status cue (below) always
# wins over a method cue -- LU 570 ("accepting Applications online") must
# stay admissible even though it names a method.
# ---------------------------------------------------------------------------

METHOD_CUE_WORDS = [
    "online", "portal", "website", "click", "the link", "click here",
    "in person at", "call our office", "call the office", "create an account",
    "by mail", "download", "apply by following", "obtained in person",
    "can be obtained",
]

# Explicit claims about current intake STATE. Presence of any of these means
# the statement is doing more than describing mechanics.
OPEN_STATE_CUE_RE = re.compile(
    r"\b(now open|currently open|are open|is open|now accepting|"
    r"currently accepting|accept(?:ing)?\s+(?:\w+\s+){0,2}applications|open now|"
    r"applications? (?:is|are) (?:currently )?open|open enrollment|"
    r"now taking applications|taking applications|being accepted|"
    r"currently\s+(?:\w+\s+){0,2}accept)\b",
    re.IGNORECASE,
)


def _has_method_cue(low):
    return any(k in low for k in METHOD_CUE_WORDS)


def _has_open_state_cue(low):
    return bool(OPEN_STATE_CUE_RE.search(low))


# ---------------------------------------------------------------------------
# Task 1, rule 3: marketing CTA with no state claim. Imperative encouragement
# with no temporal/status assertion. "Applications Are OPEN Apply NOW!!!"
# (LU 153) carries a state claim (OPEN_STATE_CUE_RE) and must survive.
# ---------------------------------------------------------------------------

CTA_ONLY_RE = re.compile(
    r"\b(start your application|start the application|apply now|"
    r"begin your application|apply today|click here to apply)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Task 1, rule 4: business/office hours. Clock times, no calendar date or
# month. Delegated to window_rules' predicate (it already handles this
# shape for windows[]) rather than reimplemented here.
# ---------------------------------------------------------------------------


def _is_office_hours_text(text):
    low = (text or "").lower()
    has_clock = bool(_CLOCK_TIME_RE.search(low))
    has_month_word = bool(_MONTH_NAME_RE.search(low))
    has_digit_date = bool(re.search(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", low)) or bool(
        re.search(r"\b\d{4}-\d{2}-\d{2}\b", low)
    )
    return has_clock and not has_month_word and not has_digit_date


# ---------------------------------------------------------------------------
# Task 1, rule 5: program mismatch. Names a non-inside program and does not
# also name the inside program.
# ---------------------------------------------------------------------------

OTHER_PROGRAM_WORDS = [
    "residential", "construction wireman", "construction electrician",
    "vdv", "telecommunications", "sound and communication",
    "sound & communication", "limited energy", "lineman", "outside",
    # round 6, task 2: journeyman CONTINUING EDUCATION is a distinct track
    # from apprenticeship intake -- LU 613's "Journeyman Wireman Continuing
    # Education CURRENTLY CLOSED" must not be read as apprenticeship
    # evidence. Deliberately the phrase "continuing education", not the bare
    # word "journeyman" -- "journeyman wireman apprenticeship" is the
    # standard name of the INSIDE program itself and must not be flagged.
    "continuing education",
]
_OTHER_PROGRAM_ABBR_RE = re.compile(r"\b(cw|ce)\b", re.IGNORECASE)
_INSIDE_RE = re.compile(r"\binside\b", re.IGNORECASE)


def classify_program(text):
    low = (text or "").lower()
    has_other = any(w in low for w in OTHER_PROGRAM_WORDS) or bool(_OTHER_PROGRAM_ABBR_RE.search(low))
    has_inside = bool(_INSIDE_RE.search(low))
    if has_other and not has_inside:
        return "other"
    if has_inside:
        return "inside"
    return "unspecified"


# ---------------------------------------------------------------------------
# Task 1: `asserts` -- derived from TEXT, never statement_type.
# ---------------------------------------------------------------------------

_CLOSED_CUE_RE = re.compile(
    r"\bclosed\b|no longer accepting|not accepting|\bsuspended\b|does not accept|"
    r"will not (?:be )?accept|\bno\b[^.]{0,40}\bwill be accepted\b",
    re.IGNORECASE,
)
# round 4's past-tense closure framing ("has closed" / "deadline ... passed")
# is just as much a closure assertion as the present-tense cues above --
# reused here rather than duplicated (LU 520).
_CLOSED_CUE_RE = re.compile(
    _CLOSED_CUE_RE.pattern + "|" + _PAST_FRAMING_RE.pattern, re.IGNORECASE,
)
_REOPEN_CUE_RE = re.compile(
    r"reopen|next\s+(application\s+)?period\s+(will\s+)?begin|"
    r"will\s+begin\s+accepting|applications\s+will\s+resume|"
    r"next\s+term\s+will\s+be\s+announced",
    re.IGNORECASE,
)
_NEGATED_OPEN_RE = re.compile(
    r"not\s+(currently\s+)?(open|accepting)\b", re.IGNORECASE,
)
# Task 2: an application deadline is folded into a sentence whose actual
# subject is TEST/COHORT ELIGIBILITY, not intake status. LU 234: "To be
# eligible for the next aptitude test in February 2027, applications must be
# received...". Narrow, tuned to this shape rather than a broad "test" ban --
# see window_rules._TESTING_SCHEDULE_RE for the equivalent window-side trap.
_AMBIGUOUS_ELIGIBILITY_RE = re.compile(
    r"eligible for (the )?next\s+\S+\s+(test|exam)", re.IGNORECASE,
)
# A statement carrying a reopen-announcement date is asserts=='closed' when
# it also asserts closure (LU 466: "2026 APPLICATION PERIOD HAS CLOSED. NEXT
# APPLICATION PERIOD WILL BEGIN JANUARY 4TH, OF 2027.") -- the reopen date
# must not be misread by classify_closure_scope() as a future_period closure
# scope (task 3's LU 466 fix; see compute_status.py).
REOPEN_ANNOUNCEMENT_IN_CLOSED_RE = _REOPEN_CUE_RE


def _derive_asserts(text):
    low = (text or "").lower()
    if classify_intake(text) in ("continuous", "periodic"):
        return "rolling"
    if _CLOSED_CUE_RE.search(low):
        return "closed"
    if _REOPEN_CUE_RE.search(low):
        return "reopening"
    if _AMBIGUOUS_ELIGIBILITY_RE.search(low):
        return "none"
    # Deliberately a fixed phrase list (OPEN_STATE_CUE_RE), not a bare
    # "open"/"accept" word-stem scan: a loose stem match fires on text that
    # merely mentions "open" in a non-affirmative way ("we do not have
    # scheduled dates for when the next application period will open") or on
    # method-only prose that happens to use "accepted" in passing. Every
    # named regression guard in this round's spec (LU 68/570/38/236/etc.) is
    # covered by one of the explicit phrases below; nothing broader is safe.
    has_open = bool(_has_open_state_cue(low))
    if has_open and _NEGATED_OPEN_RE.search(low):
        return "none"
    if has_open:
        return "open"
    return "none"


# ---------------------------------------------------------------------------
# Task 1: tense. Lightweight heuristic for the audit CSV -- not load-bearing
# for status resolution (compute_status keeps its own stated_effective_date
# comparisons for that).
# ---------------------------------------------------------------------------

_PAST_TENSE_RE = re.compile(
    r"has closed|was closed|has passed|deadline[^.]{0,40}passed|closed as of",
    re.IGNORECASE,
)
_FUTURE_TENSE_RE = re.compile(
    r"\bwill\b|\bwill be\b|starting|beginning\s+\w+\s+\d{4}", re.IGNORECASE,
)
_PRESENT_TENSE_RE = re.compile(
    r"\bis\b|\bare\b|\bnow\b|currently|\bopen\b|\bclosed\b", re.IGNORECASE,
)


def _classify_tense(text):
    low = (text or "").lower()
    if _PAST_TENSE_RE.search(low):
        return "past"
    if _FUTURE_TENSE_RE.search(low):
        return "future"
    if _PRESENT_TENSE_RE.search(low):
        return "present"
    return "unknown"


# ---------------------------------------------------------------------------
# Task 2: embedded date extraction.
# ---------------------------------------------------------------------------

_MONTH_ALT = "|".join(MONTH_NUM)

# "March 31, 2025" / "March 31st, 2025" / "April 10th 2026"
_MONTH_DAY_YEAR_RE = re.compile(
    rf"\b({_MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
# "3/31/2025" or "3/31/25"
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
# "2025-03-31"
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# bare month + year, no day: "August of 2027", "February 2027"
_MONTH_YEAR_BARE_RE = re.compile(
    rf"\b({_MONTH_ALT})\s+(?:of\s+)?(\d{{4}})\b", re.IGNORECASE,
)
# cohort references: "Class of 2030", "2027-2028 school year", "2026-2027 term"
_CLASS_OF_RE = re.compile(r"\bclass of\s+(\d{4})\b", re.IGNORECASE)
_SCHOOL_YEAR_RE = re.compile(r"\b(\d{4})\s*[-–]\s*(\d{4})\s+(school year|term|class)\b", re.IGNORECASE)

# Bound (deadline) cues occurring near a date.
_BOUND_CUE_RE = re.compile(
    r"deadline|due|until|no later than|before|postmarked|by\s+\w+\s+\d",
    re.IGNORECASE,
)
# Start cues occurring near a date.
_START_CUE_RE = re.compile(r"start(?:ing|s)?|begin(?:ning|s)?", re.IGNORECASE)


def _last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]


def _context_window(text, start, end, radius=40):
    return text[max(0, start - radius): min(len(text), end + radius)]


def extract_embedded_dates(text):
    """Returns a list of dicts: {"date": date, "role": 'bound'|'start'|
    'cohort'|'ambiguous', "month_inferred": bool}. Best-effort regex parse,
    demote-safe: anything unclear is 'ambiguous' and never drives a status
    change on its own."""
    text = text or ""
    results = []
    consumed = []  # (start, end) spans already matched by a more specific pattern

    def overlaps(s, e):
        return any(not (e <= cs or s >= ce) for cs, ce in consumed)

    # cohort patterns first, so their spans are excluded from bound/start reads
    for m in _CLASS_OF_RE.finditer(text):
        year = int(m.group(1))
        results.append({"date": datetime.date(year, 1, 1), "role": "cohort", "month_inferred": True})
        consumed.append(m.span())
    for m in _SCHOOL_YEAR_RE.finditer(text):
        year = int(m.group(1))
        results.append({"date": datetime.date(year, 1, 1), "role": "cohort", "month_inferred": True})
        consumed.append(m.span())

    # full month/day/year
    for m in _MONTH_DAY_YEAR_RE.finditer(text):
        if overlaps(*m.span()):
            continue
        month = MONTH_NUM[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        consumed.append(m.span())
        role = _classify_role(text, m.span())
        results.append({"date": d, "role": role, "month_inferred": False})

    # slash dates
    for m in _SLASH_DATE_RE.finditer(text):
        if overlaps(*m.span()):
            continue
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        consumed.append(m.span())
        role = _classify_role(text, m.span())
        results.append({"date": d, "role": role, "month_inferred": False})

    # ISO dates
    for m in _ISO_DATE_RE.finditer(text):
        if overlaps(*m.span()):
            continue
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        consumed.append(m.span())
        role = _classify_role(text, m.span())
        results.append({"date": d, "role": role, "month_inferred": False})

    # bare month + year (no day) -- lowest priority, only if not already consumed
    for m in _MONTH_YEAR_BARE_RE.finditer(text):
        if overlaps(*m.span()):
            continue
        month = MONTH_NUM[m.group(1).lower()]
        year = int(m.group(2))
        consumed.append(m.span())
        role = _classify_role(text, m.span())
        if role == "bound":
            d = datetime.date(year, month, _last_day_of_month(year, month))
        elif role == "start":
            d = datetime.date(year, month, 1)
        else:
            d = datetime.date(year, month, 1)
        results.append({"date": d, "role": role, "month_inferred": True})

    return results


def _classify_role(text, span):
    ctx = _context_window(text, span[0], span[1]).lower()
    is_bound = bool(_BOUND_CUE_RE.search(ctx))
    is_start = bool(_START_CUE_RE.search(ctx))
    if is_bound and not is_start:
        return "bound"
    if is_start and not is_bound:
        return "start"
    if is_bound and is_start:
        return "ambiguous"
    return "ambiguous"


# ---------------------------------------------------------------------------
# Task 1: the gate itself.
# ---------------------------------------------------------------------------


def admit_statement(stmt, today):
    text = stmt.get("verbatim_text", "") or ""
    low = text.lower()

    asserts = _derive_asserts(text)
    tense = _classify_tense(text)
    program = classify_program(text)
    embedded = extract_embedded_dates(text)
    embedded_dates = [e["date"] for e in embedded]

    scope = classify_closure_scope(text, today) if asserts == "closed" else ""

    # embedded_date_conflict: an admitted-open assertion whose own bound has
    # already passed (LU 26: "currently being accepted" + deadline in 2025).
    embedded_date_conflict = False
    if asserts == "open":
        for e in embedded:
            if e["role"] == "bound" and e["date"] < today:
                embedded_date_conflict = True

    admissible = True
    reject_reason = ""

    # Order matters. A statement that already carries an independent state
    # claim (asserts != 'none' -- 'open' via an explicit cue, or 'closed'/
    # 'reopening'/'rolling') is never method-only or CTA-only by definition:
    # those two rules exist specifically to catch text that asserts NOTHING
    # about intake state. LU 153 ("Applications Are OPEN Apply NOW!!!") has
    # asserts=='open' and must survive the CTA check; LU 728's "...are
    # closed" has asserts=='closed' and must survive the method-cue ("online")
    # false trigger. Office-hours and program-mismatch are unconditional --
    # a clock-only schedule or an off-target program is disqualifying no
    # matter what the text otherwise claims.
    # The subject requirement exists to keep vague, non-application temporal
    # language from masquerading as intake evidence (round 2's original
    # motivation) -- it is only meaningful when the text's assertion is
    # otherwise unclear. A statement that already unambiguously asserts
    # closed/reopening/rolling (round 1-4's existing, terser fixture texts:
    # "they will reopen November 2nd, 2026", "The apprenticeship list is
    # closed.") does not need to additionally spell out "application" to
    # count -- gating those on this vocabulary would be a new, narrower
    # requirement round 1-4 never had, not a preservation of it.
    if asserts in ("open", "none") and not _has_application_subject(low):
        admissible = False
        reject_reason = "no_application_subject"
    elif _is_office_hours_text(text):
        admissible = False
        reject_reason = "office_hours"
    elif asserts == "none" and _has_method_cue(low):
        admissible = False
        reject_reason = "method_only"
    elif asserts == "none" and CTA_ONLY_RE.search(low):
        admissible = False
        reject_reason = "cta_only"
    elif program == "other":
        admissible = False
        reject_reason = "program_mismatch"

    return {
        "admissible": admissible,
        "reject_reason": reject_reason,
        "asserts": asserts,
        "embedded_dates": embedded_dates,
        "embedded_bounds": embedded,
        "tense": tense,
        "scope": scope,
        "program": program,
        "embedded_date_conflict": embedded_date_conflict,
    }


# ---------------------------------------------------------------------------
# Round 6, task 4: de-duplicate statements that are the same sentence emitted
# under more than one statement_type label (LU 567 emits its one sentence
# twice, as 'closed' and as 'reopening'). Two copies of one sentence must not
# be counted as two independent pieces of evidence by the round-2 conflicting
# rule or round-5's corroboration logic.
# ---------------------------------------------------------------------------


def normalise_statement_text(text):
    """Collapse whitespace, strip punctuation, lowercase -- the dedup key."""
    low = (text or "").lower()
    low = re.sub(r"[^\w\s]", "", low)
    low = re.sub(r"\s+", " ", low).strip()
    return low


def statement_labels(s):
    """Every statement_type label a (possibly merged) statement carries.
    Un-merged statements just carry their own single label."""
    return s.get("combined_types") or [s.get("statement_type")]


def dedupe_statements(statements):
    """Collapses statements sharing a normalised verbatim_text into one
    record carrying every statement_type seen (in `combined_types`), keeping
    the first copy's fields otherwise -- except stated_effective_date, which
    is backfilled from a duplicate if the first copy left it empty (LU 567:
    the 'closed'-labeled copy has stated_effective_date=None, the
    'reopening'-labeled copy has the real date; the merged record must keep
    that date regardless of which copy happened to come first).

    Returns (deduped_statements, audit_rows). audit_rows only contains
    entries for groups with duplicate_count > 1: dicts with normalised_text,
    duplicate_count, statement_types, kept_asserts (of the merged text, via
    admit_statement -- caller fills today), original_statements (the raw
    group, for callers that want more detail).
    """
    groups = {}
    order = []
    for s in statements:
        key = normalise_statement_text(s.get("verbatim_text", ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)

    deduped = []
    audit_rows = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            deduped.append(group[0])
            continue
        labels = []
        for g in group:
            for lbl in statement_labels(g):
                if lbl not in labels:
                    labels.append(lbl)
        merged = dict(group[0])
        merged["combined_types"] = labels
        if not merged.get("stated_effective_date"):
            for g in group:
                if g.get("stated_effective_date"):
                    merged["stated_effective_date"] = g["stated_effective_date"]
                    break
        deduped.append(merged)
        audit_rows.append({
            "normalised_text": key,
            "duplicate_count": len(group),
            "statement_types": "|".join(labels),
            "merged_statement": merged,
            "original_statements": group,
        })
    return deduped, audit_rows
