# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/build_target_classification_audit.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

"""out/target_classification_audit.csv -- audit the 245 class-i targets for
locals that should not be offered as an inside apprenticeship (frontend task 1).

Zero network. Reads out/targets_with_population.csv and out/jurisdictions.csv only.
"""
import csv
import math
import statistics
from collections import defaultdict

csv.field_size_limit(10_000_000)


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


targets = load("out/targets_with_population.csv")
jurisdictions = load("out/jurisdictions.csv")

inside_counties = defaultdict(int)
for r in jurisdictions:
    if (r.get("jurisdiction_type") or "").strip().upper() == "I":
        inside_counties[r["local_union_id"]] += 1

# median inside population within an order-of-magnitude OLMS membership bucket
def bucket(members):
    if members <= 0:
        return 0
    return int(math.log10(members))

by_bucket = defaultdict(list)
for t in targets:
    try:
        members = float(t["olms_members"] or 0)
    except ValueError:
        members = 0
    pop = int(float(t["population_current_served_inside"] or 0))
    by_bucket[bucket(members)].append(pop)

bucket_median = {b: statistics.median(v) for b, v in by_bucket.items() if v}

rows = []
excluded = []
for t in targets:
    lid, lu = t["local_union_id"], t["lu_number"]
    trade_classes = t.get("trade_classes", "")
    classes = [c.strip() for c in trade_classes.split(",") if c.strip()]
    has_i = "i" in classes
    has_ou = ("o" in classes) or ("u" in classes)
    inside_pop = int(float(t["population_current_served_inside"] or 0))
    county_n = inside_counties.get(lid, 0)
    try:
        members = float(t["olms_members"] or 0)
    except ValueError:
        members = 0
    med = bucket_median.get(bucket(members))

    reasons = []
    if county_n == 0 or inside_pop == 0:
        reasons.append("zero inside counties/population")
    if not has_i:
        reasons.append("trade_classes lacks 'i'")
    if has_ou and not has_i:
        reasons.append("trade_classes has o/u but not i")
    if med and inside_pop > 0 and inside_pop < med / 10:
        reasons.append(f"inside population {inside_pop:,} is >10x below bucket median {int(med):,}")

    suspect = bool(reasons)
    row = {
        "local_union_id": lid,
        "lu_number": lu,
        "charter_city": t["charter_city"],
        "charter_state": t["charter_state"],
        "trade_classes": trade_classes,
        "inside_county_count": county_n,
        "inside_population": inside_pop,
        "zip_count": "",  # filled in below from zip_to_local.csv
        "has_i_class": has_i,
        "suspect_flag": suspect,
        "suspect_reason": "; ".join(reasons),
    }
    rows.append(row)
    if county_n == 0 or inside_pop == 0:
        excluded.append((lu, t["charter_city"], t["charter_state"], inside_pop))

# zip counts
zip_by_local = defaultdict(set)
for r in load("out/zip_to_local.csv"):
    zip_by_local[r["local_union_id"]].add(r["zip"].zfill(5))
for row in rows:
    row["zip_count"] = len(zip_by_local.get(row["local_union_id"], ()))

with open("out/target_classification_audit.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

n_suspect = sum(1 for r in rows if r["suspect_flag"])
print(f"targets audited: {len(rows)}")
print(f"suspect: {n_suspect}")
print(f"excluded (zero inside county/population): {len(excluded)}")
for lu, city, st, pop in excluded:
    print(f"   LU {lu}  {city}, {st}  inside_pop={pop}")
