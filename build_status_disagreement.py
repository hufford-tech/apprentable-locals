"""
Cross-validate our computed_status against the competitor's published
sparky_status for the locals they cover. Their status is a second opinion
from someone with better trade access, NOT ground truth -- disagreements
are a prioritized review queue, not a list of our errors.
"""
import csv
import json

from compute_status import compute_status
from build_verify_worklist import pick_decisive_evidence
import datetime

OUT_PATH = "out/status_disagreement.csv"

# ---------------------------------------------------------------------------
# Vocabulary mapping. Sparky publishes exactly 5 values (verified):
#   Always accepting, Open now, Closed, Window scheduled, Watching
# Ours has 8 (see compute_status.py docstring). Only some pairs are
# semantically comparable -- everything else is 'not_comparable', never
# forced into agree/disagree.
#
#   mine            <-> theirs                     rationale
#   rolling         <-> 'Always accepting'          both mean continuous/ongoing intake
#   open            <-> 'Open now'                  both mean a live dated window today
#   closed          <-> 'Closed'                    both mean explicit closure, no reopen known
#   closed_pending  <-> 'Window scheduled'           both mean a future open date is known
#   expected_open   <-> 'Watching'                  both mean "should have reopened by now,
#                                                     someone should be watching for it"
#   conflicting     <-> (none)                       ours only -- contradictory extraction
#   expired_data    <-> (none)                       ours only -- stale window, nothing newer
#   unknown         <-> (none)                       ours only -- no usable evidence
# ---------------------------------------------------------------------------
COMPARABLE_MAP = {
    "rolling": "Always accepting",
    "open": "Open now",
    "closed": "Closed",
    "closed_pending": "Window scheduled",
    "expected_open": "Watching",
}


def main():
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

    with open("../ibew-prep/sparky_coverage_117.csv", encoding="utf-8") as f:
        sparky = {r["local_number"]: r["sparky_status"] for r in csv.DictReader(f)}

    today = datetime.date.today()
    out_rows = []
    agree = 0
    disagree = 0
    not_comparable = 0
    overlap = 0

    for lu, theirs in sparky.items():
        r = extraction.get(lu)
        if r is None:
            continue  # no extraction for this local (LU 43/106/306/257/349) -- out of scope
        overlap += 1

        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})

        windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
        statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
        record = {"windows": windows, "status_statements": statements, "page_last_updated": r.get("page_last_updated") or None}
        cs = compute_status(record)
        mine = cs["computed_status"]

        expected_theirs = COMPARABLE_MAP.get(mine)
        if expected_theirs is None:
            agreement = "not_comparable"
            not_comparable += 1
        elif theirs == expected_theirs:
            agreement = "agree"
            agree += 1
        else:
            agreement = "disagree"
            disagree += 1

        quote, source_url = pick_decisive_evidence(mine, today, windows, statements)

        out_rows.append({
            "local_union_id": local_union_id,
            "lu_number": lu,
            "charter_city": p.get("charter_city", ""),
            "population_current_served_inside": p.get("population_current_served_inside", ""),
            "my_computed_status": mine,
            "my_status_confidence": cs["status_confidence"],
            "my_intake_pattern": cs.get("intake_pattern", ""),
            "their_status": theirs,
            "agreement": agreement,
            "my_evidence_quote": quote[:300],
            "my_source_url": source_url,
        })

    disagreements_only = [r for r in out_rows if r["agreement"] == "disagree"]

    def pop_val(r):
        try:
            return float(r["population_current_served_inside"] or 0)
        except (ValueError, TypeError):
            return 0.0

    disagreements_only.sort(key=pop_val, reverse=True)

    fieldnames = [
        "local_union_id", "lu_number", "charter_city", "population_current_served_inside",
        "my_computed_status", "my_status_confidence", "my_intake_pattern",
        "their_status", "agreement", "my_evidence_quote", "my_source_url",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(disagreements_only)

    comparable = agree + disagree
    print(f"Overlap (locals we both cover): {overlap}")
    print(f"Comparable (mapped vocabulary on both sides): {comparable}")
    print(f"  agree: {agree}")
    print(f"  disagree: {disagree}")
    print(f"  agreement rate (of comparable): {100*agree/comparable:.1f}%" if comparable else "  agreement rate: n/a")
    print(f"not_comparable: {not_comparable}")
    print(f"\nWrote {OUT_PATH}: {len(disagreements_only)} disagreement rows")


if __name__ == "__main__":
    main()
