import csv
from collections import defaultdict

# ---- Load town -> historical county crosswalk ----
with open("census_ct/2022tractcrosswalk.csv", encoding="utf-8-sig") as f:
    tract_rows = list(csv.DictReader(f))

town_to_county = {}
for r in tract_rows:
    town_to_county[r["town_name"].strip()] = r["county_name"].strip()

print(f"Distinct towns in crosswalk: {len(town_to_county)}")

# ---- Load current town population (SUB-EST2024, SUMLEV 061) ----
with open("census_ct/sub-est2024.csv", encoding="latin-1") as f:
    pop_rows = list(csv.DictReader(f))

ct_towns = [r for r in pop_rows if r["STATE"] == "09" and r["SUMLEV"] == "061"]
print(f"CT towns in SUB-EST2024: {len(ct_towns)}")

town_pop = {}
for r in ct_towns:
    name = r["NAME"]
    if name.endswith(" town"):
        name = name[: -len(" town")]
    town_pop[name] = int(r["POPESTIMATE2024"])

# ---- Match / aggregate ----
unmatched_towns = []
county_pop = defaultdict(int)
matched_towns = 0
for town, county in town_to_county.items():
    pop = town_pop.get(town)
    if pop is None:
        unmatched_towns.append(town)
        continue
    county_pop[county] += pop
    matched_towns += 1

print(f"Matched towns: {matched_towns}")
print(f"Unmatched towns: {len(unmatched_towns)}")
if unmatched_towns:
    print("  ", unmatched_towns)

print()
print("CT historical county populations (current, from town aggregation):")
total = 0
for county in sorted(county_pop):
    print(f"  {county} County, CT: {county_pop[county]:,}")
    total += county_pop[county]
print(f"  TOTAL (8 counties): {total:,}")

# ---- Validate against CT statewide total ----
statewide = next(r for r in pop_rows if r["STATE"] == "09" and r["SUMLEV"] == "040")
statewide_pop = int(statewide["POPESTIMATE2024"])
delta = total - statewide_pop
pct_delta = 100.0 * delta / statewide_pop
print()
print(f"CT statewide population (Census): {statewide_pop:,}")
print(f"Delta (8-county sum - statewide): {delta:,}  ({pct_delta:+.3f}%)")

# ---- Save intermediate result for downstream use ----
import json
with open("census_ct/ct_county_population_current.json", "w", encoding="utf-8") as f:
    json.dump({
        "county_pop": dict(county_pop),
        "unmatched_towns": unmatched_towns,
        "statewide_pop": statewide_pop,
        "delta": delta,
        "pct_delta": pct_delta,
    }, f, indent=2)
print()
print("Saved census_ct/ct_county_population_current.json")
