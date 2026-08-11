"""
out/verify_worklist.csv -- one row per COMPLETE local, the actual
human-verification gate artifact. shippable.csv is ZIP-shaped (26,459 rows);
verification happens per local (120 rows), so this is a separate file.

Round 2 task 7: added intake_pattern, risk_score, risk_flags so the sort
order reflects consequence-of-being-wrong, not raw population.
"""
import csv
import datetime
import json
import os

from compute_status import compute_status, _parse_date, classify_intake

OUT_PATH = "out/verify_worklist.csv"


def pick_decisive_evidence(computed_status, today, windows, statements):
    """Mirrors compute_status._determine_status's branch logic to identify
    which single window or status_statement drove the computed_status, so a
    human reviewer can check the model's call without opening the page."""
    dated_windows = [w for w in windows if w.get("precision") == "absolute" and _parse_date(w.get("open_date"))]
    rolling = [s for s in statements if s.get("statement_type") == "rolling"]
    closed = [s for s in statements if s.get("statement_type") == "closed"]
    reopening = [s for s in statements if s.get("statement_type") == "reopening"]

    if computed_status == "conflicting":
        # the rolling claim is the one being overridden -- show it, it's what
        # a human needs to weigh against the closed/reopening claim on the page
        s = rolling[0] if rolling else (closed + reopening)[0]
        return s.get("verbatim_text", ""), s.get("source_url", "")

    if computed_status == "rolling":
        s = rolling[0]
        return s.get("verbatim_text", ""), s.get("source_url", "")

    if computed_status == "open":
        for w in dated_windows:
            od, cd = _parse_date(w.get("open_date")), _parse_date(w.get("close_date"))
            if od and od <= today and (cd is None or today <= cd):
                return w.get("evidence_quote", ""), w.get("source_url", "")

    if computed_status == "closed_pending":
        future_windows = [w for w in dated_windows if _parse_date(w.get("open_date")) > today]
        if future_windows:
            w = min(future_windows, key=lambda w: _parse_date(w.get("open_date")))
            return w.get("evidence_quote", ""), w.get("source_url", "")
        future_reopenings = [s for s in reopening
                              if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) > today]
        if future_reopenings:
            s = min(future_reopenings, key=lambda s: _parse_date(s["stated_effective_date"]))
            return s.get("verbatim_text", ""), s.get("source_url", "")

    if computed_status == "expected_open":
        past_reopenings = [s for s in reopening
                            if _parse_date(s.get("stated_effective_date")) and _parse_date(s.get("stated_effective_date")) <= today]
        if past_reopenings:
            s = max(past_reopenings, key=lambda s: _parse_date(s["stated_effective_date"]))
            return s.get("verbatim_text", ""), s.get("source_url", "")

    if computed_status == "expired_data":
        past_closed = [w for w in dated_windows
                        if _parse_date(w.get("close_date")) and _parse_date(w.get("close_date")) < today]
        if past_closed:
            w = max(past_closed, key=lambda w: _parse_date(w["close_date"]))
            return w.get("evidence_quote", ""), w.get("source_url", "")

    if computed_status == "closed":
        if closed:
            s = closed[0]
            return s.get("verbatim_text", ""), s.get("source_url", "")

    return "", ""


def load_flagged_lus(path, flag_col, value_true, reason_col=None, reason_value=None):
    """Returns a set of lu_number that have >=1 row matching the flag condition
    (optionally restricted to a specific reason)."""
    flagged = set()
    if not os.path.exists(path):
        return flagged
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get(flag_col) != value_true:
                continue
            if reason_col and reason_value and r.get(reason_col) != reason_value:
                continue
            flagged.add(r["lu_number"])
    return flagged


def rolling_gate_outcome(statements):
    """Round 3, task 4. The method_only_rolling flag means "the task-1 gate
    actually changed this local's outcome" -- i.e. it has >=1 rolling
    statement that classifies 'none' AND has NO surviving rolling evidence
    (every rolling statement was method-only). A local with a mix of junk
    and genuine rolling statements (LU 20: one method-only + two genuine
    year-round statements) is fine -- it survives as 'rolling' on the
    genuine ones and doesn't belong in a risk queue for this reason.
    Returns (method_only_rolling: bool, has_mixed_quality_statements: bool)."""
    rolling = [s for s in statements if s.get("statement_type") == "rolling"]
    if not rolling:
        return False, False
    classes = [classify_intake(s.get("verbatim_text", "")) for s in rolling]
    none_count = sum(1 for c in classes if c == "none")
    surviving_count = len(classes) - none_count
    method_only_rolling = none_count > 0 and surviving_count == 0
    has_mixed_quality_statements = none_count > 0 and surviving_count > 0
    return method_only_rolling, has_mixed_quality_statements


def main():
    with open("raw/scrape/complete_lus.json", encoding="utf-8") as f:
        complete_lus = set(json.load(f))

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

    # -- round 2 risk inputs, built by tasks 3/4/6 in this same round --
    statement_disagreement_lus = load_flagged_lus(
        "out/statement_label_audit.csv", "disagreement_flag", "True",
    )
    suspect_window_lus = load_flagged_lus(
        "out/window_label_audit.csv", "suspect_flag", "True",
    )
    competitor_disagreement_lus = set()
    if os.path.exists("out/status_disagreement.csv"):
        with open("out/status_disagreement.csv", encoding="utf-8") as f:
            competitor_disagreement_lus = {r["lu_number"] for r in csv.DictReader(f) if r.get("agreement") == "disagree"}

    today = datetime.date.today()

    def pop_val(v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    rows = []
    for lu in complete_lus:
        r = extraction[lu]
        p = pop_rows.get(lu, {})
        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")

        windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
        statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
        record = {"windows": windows, "status_statements": statements, "page_last_updated": r.get("page_last_updated") or None}
        cs = compute_status(record)

        quote, source_url = pick_decisive_evidence(cs["computed_status"], today, windows, statements)
        quote = quote[:300]

        max_year = r.get("content_year", "")
        try:
            max_year_int = int(max_year) if max_year not in ("", None) else None
        except (ValueError, TypeError):
            max_year_int = None

        days_since = cs["days_since_evidence"]
        intake_pattern = cs.get("intake_pattern", "")

        method_only_rolling, has_mixed_quality_statements = rolling_gate_outcome(statements)

        # ---- risk_flags: pipe-delimited list of everything true for this local ----
        flags = []
        if method_only_rolling:
            flags.append("method_only_rolling")
        if cs["computed_status"] == "conflicting":
            flags.append("conflicting")
        if lu in statement_disagreement_lus:
            flags.append("statement_label_disagreement")
        if lu in suspect_window_lus:
            flags.append("suspect_window")
        if lu in competitor_disagreement_lus:
            flags.append("competitor_disagreement")
        if days_since is not None and days_since > 365:
            flags.append("stale_evidence")
        if days_since is None:
            flags.append("no_dated_evidence")
        if max_year_int is not None and max_year_int < 2026:
            flags.append("max_year_mentioned_lt_2026")
        if intake_pattern == "periodic":
            flags.append("periodic_intake_only")

        pop = pop_val(p.get("population_current_served_inside", ""))
        # risk_score: flag_count * (population / 100,000), rounded to 1 decimal.
        # Multiplicative and non-negative in both factors -> monotonic in both:
        # more flags always raises the score at fixed population, and more
        # population always raises the score at fixed (nonzero) flag count.
        # A local with zero flags scores 0 regardless of population -- by
        # design, since "clean, high-confidence, continuous evidence" locals
        # are exactly the ones that need the LEAST manual attention.
        risk_score = round(len(flags) * (pop / 100_000), 1)

        # round 3, task 4: has_mixed_quality_statements is informational only
        # ("worth a glance") -- shown in risk_flags but deliberately NOT
        # counted toward risk_score, unlike everything above.
        if has_mixed_quality_statements:
            flags.append("has_mixed_quality_statements")

        rows.append({
            "local_union_id": local_union_id,
            "lu_number": lu,
            "charter_city": p.get("charter_city", ""),
            "charter_state": p.get("charter_state", ""),
            "population_current_served_inside": p.get("population_current_served_inside", ""),
            "application_url": r.get("application_url", ""),
            "computed_status": cs["computed_status"],
            "status_confidence": cs["status_confidence"],
            "intake_pattern": intake_pattern,
            "days_since_evidence": days_since if days_since is not None else "",
            "max_year_mentioned": max_year,
            "window_count": r.get("window_count", ""),
            "status_statement_count": r.get("status_statement_count", ""),
            "evidence_quote": quote,
            "source_url": source_url,
            "risk_score": risk_score,
            "risk_flags": "|".join(flags),
            "verified_by": "",
            "verified_date": "",
            "verified_status": "",
            "notes": "",
            "_pop_sort": pop,
        })

    rows.sort(key=lambda r: (r["risk_score"], r["_pop_sort"]), reverse=True)
    for r in rows:
        del r["_pop_sort"]

    fieldnames = [
        "local_union_id", "lu_number", "charter_city", "charter_state",
        "population_current_served_inside", "application_url", "computed_status",
        "status_confidence", "intake_pattern", "days_since_evidence", "max_year_mentioned",
        "window_count", "status_statement_count", "evidence_quote", "source_url",
        "risk_score", "risk_flags",
        "verified_by", "verified_date", "verified_status", "notes",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {OUT_PATH}: {len(rows)} rows, sorted by risk_score descending")


if __name__ == "__main__":
    main()
