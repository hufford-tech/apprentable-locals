"""
raw/scrape/complete_lus.json (120 locals) is round-1 vintage and stale --
round 2/3 changes to compute_status moved 15+ locals off 'unknown' without
ever touching that file. This does NOT change what build_shippable.py
consumes (that's a separate decision) -- it just makes the drift visible.
"""
import csv
import json

from compute_status import compute_status

OUT_PATH = "out/complete_lus_derived.csv"


def main():
    with open("raw/scrape/complete_lus.json", encoding="utf-8") as f:
        legacy_complete_lus = set(json.load(f))

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/scrape_targets.csv", encoding="utf-8") as f:
        target_lus = [r["lu_number"] for r in csv.DictReader(f)]

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

    rows = []
    added, dropped, unchanged_complete = [], [], []

    for lu in target_lus:
        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")

        r = extraction.get(lu)
        has_application_url = bool(r and (r.get("application_url") or "").strip())

        has_resolved_status = False
        if r is not None:
            windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
            statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
            record = {"windows": windows, "status_statements": statements, "page_last_updated": r.get("page_last_updated") or None}
            cs = compute_status(record)
            has_resolved_status = cs["computed_status"] not in ("unknown", "conflicting")

        is_complete = has_application_url and has_resolved_status
        in_legacy = lu in legacy_complete_lus

        if is_complete and not in_legacy:
            delta = "added"
            added.append(lu)
        elif in_legacy and not is_complete:
            delta = "dropped"
            dropped.append(lu)
        else:
            delta = "unchanged"
            if is_complete:
                unchanged_complete.append(lu)

        rows.append({
            "local_union_id": local_union_id,
            "lu_number": lu,
            "has_application_url": has_application_url,
            "has_resolved_status": has_resolved_status,
            "is_complete": is_complete,
            "in_legacy_complete_lus": in_legacy,
            "delta": delta,
        })

    fieldnames = ["local_union_id", "lu_number", "has_application_url",
                  "has_resolved_status", "is_complete", "in_legacy_complete_lus", "delta"]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    derived_complete_count = len(added) + len(unchanged_complete)
    print(f"Legacy complete_lus.json: {len(legacy_complete_lus)}")
    print(f"Newly derived complete (has_application_url AND has_resolved_status): {derived_complete_count}")
    print(f"  unchanged (in both): {len(unchanged_complete)}")
    print(f"  added (newly complete, not in legacy): {len(added)}")
    print(f"  dropped (in legacy, no longer complete): {len(dropped)}")

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_by_lu = {r["lu_number"]: r for r in csv.DictReader(f)}

    def pop_val(lu):
        try:
            return float(pop_by_lu.get(lu, {}).get("population_current_served_inside", "") or 0)
        except (ValueError, TypeError):
            return 0.0

    print("\nADDED (city, population):")
    for lu in sorted(added, key=pop_val, reverse=True):
        p = pop_by_lu.get(lu, {})
        print(f"  LU {lu:>5}  {p.get('charter_city','?')}, {p.get('charter_state','?'):<3}  pop={pop_val(lu):>12,.0f}")

    print("\nDROPPED (city, population):")
    for lu in sorted(dropped, key=pop_val, reverse=True):
        p = pop_by_lu.get(lu, {})
        print(f"  LU {lu:>5}  {p.get('charter_city','?')}, {p.get('charter_state','?'):<3}  pop={pop_val(lu):>12,.0f}")

    print(f"\nWrote {OUT_PATH}: {len(rows)} rows")


if __name__ == "__main__":
    main()
