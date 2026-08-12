"""out/statement_dedup_audit.csv -- round 6, task 4. Every local where
dedupe_statements() collapsed >=2 status_statements sharing a normalised
verbatim_text into one merged record, plus whether that collapse alone (as
opposed to everything else changed this round) moved the computed status.

affected_status is measured by comparing compute_status() WITH dedup
(current behavior) against a version with dedupe_statements() monkeypatched
to a no-op, holding every other round-6 change constant -- isolating task 4's
own effect from tasks 1-3's.
"""
import csv
import datetime
import json

import statement_evidence
from compute_status import compute_status

OUT_PATH = "out/statement_dedup_audit.csv"


def _no_dedup(statements):
    return statements, []


def main():
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        csv.field_size_limit(10_000_000)
        rows = list(csv.DictReader(f))

    today = datetime.date(2026, 8, 10)

    out_rows = []
    real_dedupe = statement_evidence.dedupe_statements
    for r in rows:
        lu = r["lu_number"]
        windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
        statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
        if len(statements) < 2:
            continue

        _, audit_rows = real_dedupe(statements)
        if not audit_rows:
            continue

        record = {"windows": windows, "status_statements": statements,
                  "page_last_updated": r.get("page_last_updated") or None}

        with_dedup = compute_status(record, today=today)

        statement_evidence.dedupe_statements = _no_dedup
        try:
            without_dedup = compute_status(record, today=today)
        finally:
            statement_evidence.dedupe_statements = real_dedupe

        affected = (
            with_dedup["computed_status"] != without_dedup["computed_status"]
            or with_dedup["status_confidence"] != without_dedup["status_confidence"]
        )

        local_union_id = crosswalk.get(lu, "")
        for row in audit_rows:
            merged = row["merged_statement"]
            kept_asserts = statement_evidence.admit_statement(merged, today)["asserts"]
            out_rows.append({
                "local_union_id": local_union_id,
                "lu_number": lu,
                "normalised_text": row["normalised_text"][:300],
                "duplicate_count": row["duplicate_count"],
                "statement_types": row["statement_types"],
                "kept_asserts": kept_asserts,
                "affected_status": affected,
            })

    fieldnames = [
        "local_union_id", "lu_number", "normalised_text", "duplicate_count",
        "statement_types", "kept_asserts", "affected_status",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    locals_with_dupes = len({r["lu_number"] for r in out_rows})
    affected = [r for r in out_rows if r["affected_status"]]
    print(f"Wrote {OUT_PATH}: {len(out_rows)} duplicate groups across {locals_with_dupes} locals")
    print(f"Groups where dedup alone changed status/confidence: {len(affected)}")
    for r in affected:
        print(" ", r["lu_number"], r["normalised_text"][:80])


if __name__ == "__main__":
    main()
