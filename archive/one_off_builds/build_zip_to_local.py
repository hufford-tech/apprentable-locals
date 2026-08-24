import csv
from collections import defaultdict

CT_HISTORICAL_FIPS = {
    "Fairfield": "09001", "Hartford": "09003", "Litchfield": "09005",
    "Middlesex": "09007", "New Haven": "09009", "New London": "09011",
    "Tolland": "09013", "Windham": "09015",
}


def pct_to_float(p):
    p = (p or "").strip().rstrip("%")
    try:
        return float(p)
    except ValueError:
        return None


# ---- Load jurisdictions (Inside only) ----
with open("out/jurisdictions.csv", encoding="utf-8") as f:
    j_rows = list(csv.DictReader(f))

inside_rows = [r for r in j_rows if r["jurisdiction_type"] == "I"]

# Non-CT: keyed by census_fips (5-digit county FIPS)
by_fips = defaultdict(list)
for r in inside_rows:
    if r["state_province"] == "CT":
        continue
    fips = r["census_fips"].strip()
    if not fips:
        continue  # unmatched county (17 known holdouts) -- correctly excluded
    pct = pct_to_float(r["percentage"])
    by_fips[fips].append({
        "lu_number": r["lu_number"],
        "local_union_id": r["local_union_id"],
        "county_name": r["county_name"],
        "state": r["state_province"],
        "pct": pct,
    })

# CT: keyed by historical county name
ct_by_county = defaultdict(list)
for r in inside_rows:
    if r["state_province"] != "CT":
        continue
    base = r["county_name"].split(" County,")[0].strip()
    pct = pct_to_float(r["percentage"])
    ct_by_county[base].append({
        "lu_number": r["lu_number"],
        "local_union_id": r["local_union_id"],
        "county_name": r["county_name"],
        "pct": pct,
    })

print(f"Non-CT counties with Inside coverage (FIPS-keyed): {len(by_fips)}")
print(f"CT historical counties with Inside coverage: {len(ct_by_county)}")

out_rows = []

# ---- Part A: non-CT via HUD ZIP-COUNTY crosswalk ----
skipped_zero_ratio = 0
skipped_no_county_match = 0
total_hud_rows = 0
with open("hud/zip_county.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        total_hud_rows += 1
        zip_code = row["zip"].strip()
        geoid = row["geoid"].strip()
        state = row["state"].strip()
        try:
            res_ratio = float(row["res_ratio"])
        except ValueError:
            res_ratio = 0.0

        if state == "CT":
            continue  # handled separately in Part B

        if res_ratio <= 0:
            skipped_zero_ratio += 1
            continue

        candidates = by_fips.get(geoid)
        if not candidates:
            skipped_no_county_match += 1
            continue

        n = len(candidates)
        confidence = "high" if n == 1 else "low"
        for c in candidates:
            out_rows.append({
                "zip": zip_code,
                "county_fips": geoid,
                "county_name": c["county_name"],
                "state": state,
                "res_ratio": res_ratio,
                "lu_number": c["lu_number"],
                "local_union_id": c["local_union_id"],
                "county_pct_coverage": c["pct"] if c["pct"] is not None else "",
                "confidence": confidence,
                "candidate_count": n,
            })

print(f"HUD rows processed: {total_hud_rows}")
print(f"  skipped (res_ratio<=0): {skipped_zero_ratio}")
print(f"  skipped (county has no Inside-local match in our data): {skipped_no_county_match}")
print(f"  output rows so far (non-CT): {len(out_rows)}")

# ---- Part B: CT hand-map via town crosswalk ----
with open("census_ct/2022tractcrosswalk.csv", encoding="utf-8-sig") as f:
    tract_rows = list(csv.DictReader(f))

town_county = {r["town_name"].strip(): r["county_name"].strip() for r in tract_rows}

zip_towns = defaultdict(set)
for r in tract_rows:
    z = r["zip5_zcta2020"].strip()
    if z:
        zip_towns[z].add(r["town_name"].strip())

ct_multi_county_zips = []
ct_rows_added = 0
for zip_code, towns in zip_towns.items():
    counties = set(town_county[t] for t in towns)
    if len(counties) > 1:
        ct_multi_county_zips.append((zip_code, towns, counties))
        continue  # none observed in practice, but don't guess if it happens
    county = next(iter(counties))
    candidates = ct_by_county.get(county, [])
    if not candidates:
        continue
    n = len(candidates)
    confidence = "high" if n == 1 else "low"
    for c in candidates:
        out_rows.append({
            "zip": zip_code,
            "county_fips": CT_HISTORICAL_FIPS.get(county, ""),
            "county_name": c["county_name"],
            "state": "CT",
            "res_ratio": 1.0,  # every CT zip sits entirely within one historical county (verified)
            "lu_number": c["lu_number"],
            "local_union_id": c["local_union_id"],
            "county_pct_coverage": c["pct"] if c["pct"] is not None else "",
            "confidence": confidence,
            "candidate_count": n,
        })
        ct_rows_added += 1

print(f"CT zips processed: {len(zip_towns)}")
print(f"  CT zips spanning multiple historical counties (would need special handling): {len(ct_multi_county_zips)}")
print(f"  CT output rows added: {ct_rows_added}")

# ---- Write output ----
fieldnames = ["zip", "county_fips", "county_name", "state", "res_ratio",
              "lu_number", "local_union_id", "county_pct_coverage", "confidence", "candidate_count"]
with open("out/zip_to_local.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(out_rows)

print()
print(f"Wrote out/zip_to_local.csv: {len(out_rows)} rows")

distinct_zips = set(r["zip"] for r in out_rows)
ambiguous_zips = set(r["zip"] for r in out_rows if r["confidence"] == "low")
print(f"Distinct ZIPs represented: {len(distinct_zips)}")
print(f"ZIPs with at least one ambiguous (low-confidence) row: {len(ambiguous_zips)}")

# ---- Validation spot check ----
print()
print("=== VALIDATION: 60601 -> expect LU 134 ===")
for r in out_rows:
    if r["zip"] == "60601":
        print(f'  zip={r["zip"]} county={r["county_name"]} lu={r["lu_number"]} '
              f'res_ratio={r["res_ratio"]} county_pct={r["county_pct_coverage"]} '
              f'confidence={r["confidence"]} candidates={r["candidate_count"]}')
