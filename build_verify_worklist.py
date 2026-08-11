"""
out/verify_worklist.csv -- one row per COMPLETE local, the actual
human-verification gate artifact. shippable.csv is ZIP-shaped (26,459 rows);
verification happens per local (120 rows), so this is a separate file.
"""
import csv
import json

from compute_status import compute_status, _parse_date

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


def main():
    with open("raw/scrape/complete_lus.json", encoding="utf-8") as f:
        complete_lus = set(json.load(f))

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

    import datetime
    today = datetime.date.today()

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

        def pop_val(v):
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0

        rows.append({
            "local_union_id": local_union_id,
            "lu_number": lu,
            "charter_city": p.get("charter_city", ""),
            "charter_state": p.get("charter_state", ""),
            "population_current_served_inside": p.get("population_current_served_inside", ""),
            "application_url": r.get("application_url", ""),
            "computed_status": cs["computed_status"],
            "status_confidence": cs["status_confidence"],
            "days_since_evidence": cs["days_since_evidence"] if cs["days_since_evidence"] is not None else "",
            "max_year_mentioned": r.get("content_year", ""),
            "window_count": r.get("window_count", ""),
            "status_statement_count": r.get("status_statement_count", ""),
            "evidence_quote": quote,
            "source_url": source_url,
            "verified_by": "",
            "verified_date": "",
            "verified_status": "",
            "notes": "",
            "_pop_sort": pop_val(p.get("population_current_served_inside", "")),
        })

    rows.sort(key=lambda r: r["_pop_sort"], reverse=True)
    for r in rows:
        del r["_pop_sort"]

    fieldnames = [
        "local_union_id", "lu_number", "charter_city", "charter_state",
        "population_current_served_inside", "application_url", "computed_status",
        "status_confidence", "days_since_evidence", "max_year_mentioned",
        "window_count", "status_statement_count", "evidence_quote", "source_url",
        "verified_by", "verified_date", "verified_status", "notes",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {OUT_PATH}: {len(rows)} rows")


if __name__ == "__main__":
    main()
