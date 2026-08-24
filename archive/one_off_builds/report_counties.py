import csv
from collections import defaultdict

CANADIAN = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}

with open("out/jurisdictions.csv", encoding="utf-8") as f:
    j_rows = list(csv.DictReader(f))

with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
    locals_rows = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/trade_classes.csv", encoding="utf-8") as f:
    tc_rows = list(csv.DictReader(f))
tc_by_lu = defaultdict(list)
for r in tc_rows:
    tc_by_lu[r["lu_number"]].append(r["trade_class_code"])


def is_us_row(r):
    return r["state_province"].strip().upper() not in CANADIAN and r["state_province"].strip() != ""


def pct_to_float(p):
    p = (p or "").strip().rstrip("%")
    try:
        return float(p)
    except ValueError:
        return None


us_rows = [r for r in j_rows if is_us_row(r)]
ca_rows = [r for r in j_rows if not is_us_row(r) and r["state_province"].strip() != ""]

print(f"Total jurisdiction rows: {len(j_rows)}  (US: {len(us_rows)}, Canadian/other: {len(ca_rows)})")
print()

# ---------------- Section 1 ----------------
print("=== 1. Distinct counties / locals by jurisdiction type (US only) ===")
for jt in ["I", "O"]:
    rows = [r for r in us_rows if r["jurisdiction_type"] == jt]
    counties = set((r["state_province"], r["county_name"]) for r in rows)
    locals_ = set(r["lu_number"] for r in rows)
    print(f"  jurisdiction={jt}: {len(counties)} distinct counties, {len(locals_)} distinct locals")

inside_counties = set((r["state_province"], r["county_name"]) for r in us_rows if r["jurisdiction_type"] == "I")
any_counties = set((r["state_province"], r["county_name"]) for r in us_rows)
print(f"  Counties covered by an Inside local: {len(inside_counties)} (of ~3,144 US counties = {100*len(inside_counties)/3144:.1f}%)")
print(f"  Counties covered by ANY local (Inside or Outside): {len(any_counties)} (of ~3,144 = {100*len(any_counties)/3144:.1f}%)")
print()

# ---------------- Section 2 ----------------
print("=== 2. Counties with more than one Inside local (US only) ===")
inside_rows = [r for r in us_rows if r["jurisdiction_type"] == "I"]
locals_per_county = defaultdict(set)
for r in inside_rows:
    locals_per_county[(r["state_province"], r["county_name"])].add(r["lu_number"])

multi = {k: v for k, v in locals_per_county.items() if len(v) > 1}
print(f"  Counties with >1 Inside local: {len(multi)}")
dist = defaultdict(int)
for v in locals_per_county.values():
    dist[len(v)] += 1
print("  Distribution of Inside-locals-per-county:")
for n in sorted(dist):
    print(f"    {n} local(s): {dist[n]} counties")
print("  Top 10 counties by number of Inside locals:")
top10 = sorted(multi.items(), key=lambda x: -len(x[1]))[:10]
for (state, county), lus in top10:
    print(f"    {county}, {state}: {len(lus)} locals -> {sorted(lus, key=lambda x: int(x))}")
print()

# ---------------- Section 3 ----------------
print("=== 3. US locals (of 764) with zero county rows ===")
lus_with_rows = set(r["lu_number"] for r in j_rows)  # any row at all, US or CA
zero_row_lus = []
for lu, r in locals_rows.items():
    state = r["charter_state"].strip().upper()
    if state in CANADIAN:
        continue
    if lu not in lus_with_rows:
        zero_row_lus.append(lu)

print(f"  Count: {len(zero_row_lus)}")
print(f'  {"LU":6}{"City":22}{"State":6}{"Website?":9}  Trade classes')
for lu in sorted(zero_row_lus, key=lambda x: int(x)):
    r = locals_rows[lu]
    classes = ",".join(sorted(tc_by_lu.get(lu, [])))
    has_site = "yes" if r["website"].strip() else "no"
    print(f'  {lu:6}{r["charter_city"]:22}{r["charter_state"]:6}{has_site:9}  {classes}')

with open("out/scrape_targets.csv", encoding="utf-8") as f:
    target_lus = set(r["lu_number"] for r in csv.DictReader(f))
missing_i_targets = set(zero_row_lus) & target_lus
print()
print(f"  Class 'i' US target locals missing jurisdiction data: {len(missing_i_targets)}")
if missing_i_targets:
    print(f"    {sorted(missing_i_targets, key=lambda x: int(x))}")
print()

# ---------------- Section 4 ----------------
print("=== 4. Inside-only US counties where summed percentage is <95 or >105 ===")
pct_sum_by_county = defaultdict(float)
pct_has_blank = defaultdict(bool)
for r in inside_rows:
    p = pct_to_float(r["percentage"])
    key = (r["state_province"], r["county_name"])
    if p is None:
        pct_has_blank[key] = True
    else:
        pct_sum_by_county[key] += p

bad = {k: v for k, v in pct_sum_by_county.items() if (v < 95 or v > 105) and not pct_has_blank.get(k)}
print(f"  Counties out of [95,105] range (excluding those with any blank percentage): {len(bad)}")
worst = sorted(bad.items(), key=lambda x: -abs(x[1] - 100))[:10]
print("  10 worst (by distance from 100%):")
for (state, county), total in worst:
    lus_here = sorted(locals_per_county[(state, county)], key=lambda x: int(x))
    print(f"    {county}, {state}: {total:.1f}%  locals={lus_here}")
blank_count = sum(1 for v in pct_has_blank.values() if v)
print(f"  (Note: {blank_count} Inside counties have at least one blank percentage row and were excluded from this check)")
print()

# ---------------- Section 5 ----------------
print("=== 5. Population coverage, Inside only, US, deduped by county ===")
pop_by_county = {}
covering_locals_by_county = defaultdict(list)
for r in inside_rows:
    key = (r["state_province"], r["county_name"])
    try:
        pop = float(r["population"]) if r["population"].strip() else None
    except ValueError:
        pop = None
    if pop is not None:
        pop_by_county[key] = pop
    p = pct_to_float(r["percentage"])
    covering_locals_by_county[key].append((r["lu_number"], p))

total_pop = sum(pop_by_county.values())
print(f"  Total US population represented (Inside, deduped by county): {total_pop:,.0f}")
print("  Top 50 counties by population, with covering Inside local(s):")
top50 = sorted(pop_by_county.items(), key=lambda x: -x[1])[:50]
for (state, county), pop in top50:
    covers = covering_locals_by_county[key] if False else covering_locals_by_county[(state, county)]
    cover_str = ", ".join(f"LU{lu}({pct}%)" if pct is not None else f"LU{lu}(?%)" for lu, pct in covers)
    print(f"    {county}, {state}: pop={pop:,.0f}  covered by {cover_str}")
print()

# ---------------- Section 6 ----------------
print("=== 6. Population served, per scrape_targets.csv local (Inside coverage, weighted by %) ===")
with open("out/scrape_targets.csv", encoding="utf-8") as f:
    targets = list(csv.DictReader(f))

pop_served = {}
for t in targets:
    lu = t["lu_number"]
    total = 0.0
    for r in inside_rows:
        if r["lu_number"] != lu:
            continue
        key = (r["state_province"], r["county_name"])
        pop = pop_by_county.get(key)
        if pop is None:
            continue
        p = pct_to_float(r["percentage"])
        weight = (p / 100.0) if p is not None else 1.0
        total += pop * weight
    pop_served[lu] = total

rows_out = []
for t in targets:
    lu = t["lu_number"]
    row = dict(t)
    row["population_served_inside"] = f"{pop_served[lu]:.0f}"
    rows_out.append(row)

rows_out.sort(key=lambda r: -float(r["population_served_inside"]))

fieldnames = list(targets[0].keys()) + ["population_served_inside"]
with open("out/targets_with_population.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows_out)

print(f"  Wrote out/targets_with_population.csv: {len(rows_out)} rows, sorted by population served descending")
print("  Top 10:")
for r in rows_out[:10]:
    print(f'    LU{r["lu_number"]}: {float(r["population_served_inside"]):,.0f}  ({r["charter_city"]}, {r["charter_state"]})')
