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
import datetime

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


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
    rolling_statements = [s for s in statements if s.get("statement_type") == "rolling"]
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

    status, confidence = _determine_status(
        today, dated_windows, rolling_statements, closed_statements,
        reopening_statements, most_recent,
    )
    confidence = _cap_confidence(confidence, days_since_evidence)

    return {"computed_status": status, "status_confidence": confidence,
            "days_since_evidence": days_since_evidence}


def _determine_status(today, dated_windows, rolling_statements, closed_statements,
                       reopening_statements, most_recent):
    """Returns (computed_status, status_confidence) BEFORE the evidence-age
    confidence cap is applied by the caller."""

    # 1. CONFLICTING -- a rolling claim coexists with a closed/reopening claim.
    # Do not try to guess which one is current from text; surface it for a human.
    if rolling_statements and (closed_statements or reopening_statements):
        return "conflicting", "low"

    # 1b. ROLLING -- rolling claim, nothing contradicts it
    if rolling_statements:
        confidence = "high" if len(rolling_statements) == 1 and not dated_windows else "medium"
        return "rolling", confidence

    # 2. OPEN -- today inside a dated window
    for w in dated_windows:
        od = _parse_date(w.get("open_date"))
        cd = _parse_date(w.get("close_date"))
        if od and od <= today and (cd is None or today <= cd):
            return "open", "high"

    # 3. CLOSED_PENDING -- future dated window, or a reopening statement not yet arrived
    future_windows = [w for w in dated_windows if _parse_date(w.get("open_date")) > today]
    future_reopenings = [
        s for s in reopening_statements
        if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) > today
    ]
    if future_windows or future_reopenings:
        return "closed_pending", "high"

    # 4. EXPECTED_OPEN -- reopening date has passed and is the most recent evidence
    past_reopenings = [
        s for s in reopening_statements
        if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) <= today
    ]
    if past_reopenings:
        most_recent_reopen = max(_parse_date(s["stated_effective_date"]) for s in past_reopenings)
        if most_recent is None or most_recent == most_recent_reopen:
            return "expected_open", "medium"

    # 5. EXPIRED_DATA -- most recent dated window's close has passed, nothing newer
    past_windows_with_close = [
        w for w in dated_windows
        if _parse_date(w.get("close_date")) and _parse_date(w.get("close_date")) < today
    ]
    if past_windows_with_close:
        most_recent_close = max(_parse_date(w["close_date"]) for w in past_windows_with_close)
        if most_recent is None or most_recent == most_recent_close:
            return "expired_data", "medium"

    # 6. CLOSED -- explicit closure statement, no reopen date/window anywhere
    if closed_statements and not reopening_statements and not dated_windows:
        return "closed", "high"

    # 7. UNKNOWN
    return "unknown", "low"


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


if __name__ == "__main__":
    unittest.main()
