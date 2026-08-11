import csv
import json

from compute_status import compute_status

with open("raw/scrape/complete_lus.json", encoding="utf-8") as f:
    complete_lus = set(json.load(f))

with open("out/extraction_v2.csv", encoding="utf-8") as f:
    extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/targets_with_population.csv", encoding="utf-8") as f:
    pop_rows_by_lu = {r["lu_number"]: r for r in csv.DictReader(f)}

# lu_number -> local_union_id crosswalk. local_union_id is the real primary
# key; lu_number is only unique incidentally within this 242-row extraction.
crosswalk = {}
for lu, r in pop_rows_by_lu.items():
    local_union_id = r["local_union_id"]
    if lu in crosswalk and crosswalk[lu] != local_union_id:
        raise AssertionError(f"lu_number {lu} maps to multiple local_union_id values in targets_with_population.csv")
    crosswalk[lu] = local_union_id

for lu in extraction:
    if lu not in crosswalk:
        raise AssertionError(f"lu_number {lu} in extraction_v2.csv has no local_union_id in targets_with_population.csv")

pop_rows = {crosswalk[lu]: r for lu, r in pop_rows_by_lu.items()}

with open("out/zip_to_local.csv", encoding="utf-8") as f:
    zip_rows = list(csv.DictReader(f))

per_local_status = {}
for lu in complete_lus:
    r = extraction[lu]
    local_union_id = crosswalk[lu]
    windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
    statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
    record = {"windows": windows, "status_statements": statements, "page_last_updated": r.get("page_last_updated") or None}
    cs = compute_status(record)
    per_local_status[local_union_id] = {
        "computed_status": cs["computed_status"],
        "status_confidence": cs["status_confidence"],
        "days_since_evidence": cs["days_since_evidence"],
        "application_url": r.get("application_url", ""),
        # is_stale is deliberately NOT derived here. int(content_year) < current_year
        # is not a staleness test -- content_year is "highest year mentioned anywhere
        # on the page" (24 locals read 2027, some higher), not a last-modified date.
        # Real staleness needs monitor.py's hash history (last_changed). Until that
        # exists, is_stale ships empty; max_year_mentioned carries the signal instead.
        "max_year_mentioned": r.get("content_year", ""),
    }

complete_local_union_ids = {crosswalk[lu] for lu in complete_lus}

out_rows = []
for zr in zip_rows:
    local_union_id = zr["local_union_id"]
    if local_union_id not in complete_local_union_ids:
        continue
    p = pop_rows.get(local_union_id, {})
    s = per_local_status[local_union_id]
    out_rows.append({
        "zip": zr["zip"],
        "local_union_id": local_union_id,
        "lu_number": zr["lu_number"],
        "county_fips": zr["county_fips"],
        "county_name": zr["county_name"],
        "state": zr["state"],
        "res_ratio": zr["res_ratio"],
        "county_pct_coverage": zr["county_pct_coverage"],
        "zip_confidence": zr["confidence"],
        "charter_city": p.get("charter_city", ""),
        "charter_state": p.get("charter_state", ""),
        "population_current_served_inside": p.get("population_current_served_inside", ""),
        "application_url": s["application_url"],
        "computed_status": s["computed_status"],
        "status_confidence": s["status_confidence"],
        "days_since_evidence": s["days_since_evidence"],
        "is_stale": "",
        "max_year_mentioned": s["max_year_mentioned"],
    })

fieldnames = [
    "zip", "local_union_id", "lu_number", "county_fips", "county_name", "state", "res_ratio",
    "county_pct_coverage", "zip_confidence", "charter_city", "charter_state",
    "population_current_served_inside", "application_url",
    "computed_status", "status_confidence", "days_since_evidence",
    "is_stale", "max_year_mentioned",
]
with open("out/shippable.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(out_rows)

distinct_locals = set(r["local_union_id"] for r in out_rows)
print(f"Wrote out/shippable.csv: {len(out_rows)} ZIP rows covering {len(distinct_locals)} distinct locals")
missing_from_zip = complete_local_union_ids - distinct_locals
if missing_from_zip:
    print(f"COMPLETE locals with NO zip_to_local.csv rows (dropped from shippable set): {sorted(missing_from_zip)}")
