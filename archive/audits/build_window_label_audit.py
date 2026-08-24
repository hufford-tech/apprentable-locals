# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/build_window_label_audit.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

"""
Audit every window across all 242 locals for the office-hours-stored-as-
application-window defect (LU 531, 159, 601) and related structural problems.
"""
import csv
import json

from compute_status import compute_status
from window_rules import is_suspect_window

OUT_PATH = "out/window_label_audit.csv"


def main():
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # user's prior belief (computed against the pre-task-1-gate baseline, unknown=116)
    NAMED_UNKNOWN_NONABS = ["490", "231", "82", "305", "7", "73", "449"]

    out_rows = []
    unknown_nonabs_locals = set()   # independently recomputed against CURRENT (post-gate) state
    survivor_locals = set()

    for r in rows:
        lu = r["lu_number"]
        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})
        try:
            pop_val = float(p.get("population_current_served_inside", "") or 0)
        except (ValueError, TypeError):
            pop_val = 0.0

        windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
        statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
        record = {"windows": windows, "status_statements": statements, "page_last_updated": r.get("page_last_updated") or None}
        cs = compute_status(record)
        has_nonabs_window = any(w.get("precision") != "absolute" for w in windows)
        is_unknown_nonabs = cs["computed_status"] == "unknown" and has_nonabs_window
        if is_unknown_nonabs:
            unknown_nonabs_locals.add(lu)

        for w in windows:
            flag, reason = is_suspect_window(w)
            if is_unknown_nonabs and w.get("precision") != "absolute" and not flag:
                survivor_locals.add(lu)

            out_rows.append({
                "local_union_id": local_union_id,
                "lu_number": lu,
                "precision": w.get("precision", ""),
                "open_date": w.get("open_date", ""),
                "close_date": w.get("close_date", ""),
                "open_month": w.get("open_month", ""),
                "open_day": w.get("open_day", ""),
                "close_month": w.get("close_month", ""),
                "close_day": w.get("close_day", ""),
                "is_recurring_annual": w.get("is_recurring_annual", ""),
                "relative_description": (w.get("relative_description") or "")[:300],
                "evidence_quote": (w.get("evidence_quote") or "")[:300],
                "source_url": w.get("source_url", ""),
                "suspect_flag": str(flag),
                "suspect_reason": reason,
                "_pop_sort": pop_val,
                "_suspect_sort": 0 if flag else 1,
            })

    out_rows.sort(key=lambda r: (r["_suspect_sort"], -r["_pop_sort"]))
    for r in out_rows:
        del r["_pop_sort"]
        del r["_suspect_sort"]

    fieldnames = [
        "local_union_id", "lu_number", "precision", "open_date", "close_date",
        "open_month", "open_day", "close_month", "close_day", "is_recurring_annual",
        "relative_description", "evidence_quote", "source_url",
        "suspect_flag", "suspect_reason",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    total_flagged = sum(1 for r in out_rows if r["suspect_flag"] == "True")
    print(f"Wrote {OUT_PATH}: {len(out_rows)} windows, {total_flagged} flagged")

    print(f"\nIndependently recomputed against CURRENT (post-round-2-gate) state:")
    print(f"  'unknown' locals with >=1 non-absolute window: {len(unknown_nonabs_locals)} "
          f"{sorted(unknown_nonabs_locals, key=int)}")
    print(f"  of those, locals with >=1 window surviving this audit as genuine: "
          f"{len(survivor_locals)} {sorted(survivor_locals, key=int)}")
    print(f"\nUser's prior belief (pre-round-2-gate baseline): ~30 unknown/non-absolute locals, "
          f"~7 survivors named {NAMED_UNKNOWN_NONABS}")
    named_set = set(NAMED_UNKNOWN_NONABS)
    print(f"  match: {survivor_locals == named_set}  "
          f"(named-but-not-found: {sorted(named_set - survivor_locals, key=int)}, "
          f"found-but-not-named: {sorted(survivor_locals - named_set, key=int)})")


if __name__ == "__main__":
    main()
