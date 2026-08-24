"""
RAPIDS round 1, Task 1 follow-up: close the remaining gaps in the LU-number/city
join by using out/zip_to_local.csv -- the repo's own validated ZIP-to-jurisdiction
map -- instead of a distance/radius guess.

Only touches locals that rapids_locals_join.csv left as no_match or
no_state_candidates. Does not re-derive the universe or re-run the LU/city pass;
reads their output and extends it.

A ZIP can straddle more than one jurisdiction (20,926 of 56,177 rows in
zip_to_local.csv share a ZIP with another row), so a program's ZIP can imply more
than one candidate lu_number. This merges rather than doing a single-valued
lookup, so every jurisdiction claim on a program's ZIP becomes its own row.

Confidence-gated on purpose, same candidate-vs-confirmed pattern as monitor.py:
"high" confidence zip claims are auto-accepted. "low" confidence claims are NOT --
checked and found to be wrong 100% of the time in the first pass (6 of 6 low-
confidence matches were bad, including two cases where the same program got
credited to two different locals, and one where the matched program's own name
named a different LU than the one it was assigned to). Low-confidence candidates
are written to a separate review file instead of the main join, for a human to
resolve, not auto-promoted.

Also guards against the failure mode that produced those errors even within
"high" confidence: if the same PS_ID ends up the best candidate for more than one
local, that is flagged and excluded from auto-accept rather than silently kept,
since one physical program address should not back two different locals.

Owns: out/rapids_locals_join.csv (rewritten with the extra pass appended),
out/rapids_zip_join_detail.csv (audit trail of accepted matches),
out/rapids_zip_join_needs_review.csv (low-confidence and colliding candidates,
not auto-accepted).
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"


def main():
    universe_path = OUT / "rapids_universe.csv"
    join_path = OUT / "rapids_locals_join.csv"
    zip_path = OUT / "zip_to_local.csv"

    for p in (universe_path, join_path, zip_path):
        if not p.exists():
            print(f"[blocker] missing required file: {p}", file=sys.stderr)
            raise SystemExit(1)

    universe = pd.read_csv(universe_path, dtype=str, low_memory=False)
    join = pd.read_csv(join_path, dtype=str, low_memory=False)
    zip_to_local = pd.read_csv(zip_path, dtype=str, low_memory=False)

    zip_to_local["zip"] = zip_to_local["zip"].str.strip().str.zfill(5)
    universe["PROG_ZIP5"] = universe["PROG_ZIP5"].str.strip().str.zfill(5)

    gap_mask = join["match_type"].isin(["no_match", "no_state_candidates"])
    gaps = join[gap_mask].copy()
    print(f"Attempting zip-jurisdiction match for {len(gaps)} unmatched locals")

    universe = universe.merge(
        zip_to_local[["zip", "lu_number", "confidence"]].rename(
            columns={"lu_number": "jurisdiction_lu", "confidence": "jurisdiction_confidence"}
        ),
        left_on="PROG_ZIP5", right_on="zip", how="left",
    )

    # First pass: collect every candidate (any confidence) per gap local, so we
    # can detect a program claimed by more than one local before deciding what
    # to auto-accept.
    raw_candidates = {}
    for _, gap in gaps.iterrows():
        lu = gap["lu_number"]
        cands = universe[universe["jurisdiction_lu"] == lu]
        if len(cands):
            raw_candidates[lu] = cands

    # Which PS_IDs get claimed by more than one different local at all?
    ps_id_to_lus = {}
    for lu, cands in raw_candidates.items():
        for ps_id in cands["PS_ID"].unique():
            ps_id_to_lus.setdefault(ps_id, set()).add(lu)
    colliding_ps_ids = {ps for ps, lus in ps_id_to_lus.items() if len(lus) > 1}

    accepted_rows = []
    review_rows = []

    for lu, cands in raw_candidates.items():
        gap_row = gaps[gaps["lu_number"] == lu].iloc[0]
        idx = gaps[gaps["lu_number"] == lu].index[0]

        c = cands.copy()
        c["_conf_rank"] = c["jurisdiction_confidence"].map({"high": 0, "medium": 1, "low": 2}).fillna(3)
        c["_status_rank"] = c["PROG_STATUS"].map({"Registered": 0}).fillna(1)
        c = c.sort_values(["_conf_rank", "_status_rank"])
        best = c.iloc[0]

        record = {
            "lu_number": lu, "local_city": gap_row["local_city"], "local_state": gap_row["local_state"],
            "matched_ps_id": best["PS_ID"], "matched_name": best["PROG_NAME"],
            "matched_zip": best["PROG_ZIP5"], "jurisdiction_confidence": best["jurisdiction_confidence"],
            "candidate_count_for_this_local": len(c),
        }

        if best["jurisdiction_confidence"] != "high" or best["PS_ID"] in colliding_ps_ids:
            reason = []
            if best["jurisdiction_confidence"] != "high":
                reason.append(f"confidence={best['jurisdiction_confidence']}")
            if best["PS_ID"] in colliding_ps_ids:
                other_lus = colliding_ps_ids and (ps_id_to_lus[best["PS_ID"]] - {lu})
                reason.append(f"program also claimed by lu {sorted(other_lus)}")
            record["review_reason"] = "; ".join(reason)
            review_rows.append(record)
            continue

        join.loc[idx, "match_type"] = "zip_jurisdiction_match"
        join.loc[idx, "rapids_ps_id"] = best["PS_ID"]
        join.loc[idx, "rapids_name"] = best["PROG_NAME"]
        join.loc[idx, "rapids_city"] = best["PROG_CITY"]
        join.loc[idx, "rapids_state"] = best["PROG_STATE"]
        join.loc[idx, "rapids_status"] = best["PROG_STATUS"]
        join.loc[idx, "score"] = None
        accepted_rows.append(record)

    join.to_csv(join_path, index=False)
    pd.DataFrame(accepted_rows).to_csv(OUT / "rapids_zip_join_detail.csv", index=False)
    pd.DataFrame(review_rows).to_csv(OUT / "rapids_zip_join_needs_review.csv", index=False)

    counts = join["match_type"].value_counts()
    matched = join["match_type"].isin(
        ["lu_number_match", "city_fuzzy_match", "zip_jurisdiction_match"]
    ).sum()
    total = len(join)
    print(f"Auto-accepted {len(accepted_rows)} additional locals via high-confidence ZIP jurisdiction")
    print(f"Routed {len(review_rows)} to manual review (low confidence and/or colliding program)")
    print(f"Total matched: {matched} / {total} ({matched/total:.1%})")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    print()
    print("Files touched:")
    print("  out/rapids_locals_join.csv (updated in place)")
    print("  out/rapids_zip_join_detail.csv")
    print("  out/rapids_zip_join_needs_review.csv")


if __name__ == "__main__":
    main()
