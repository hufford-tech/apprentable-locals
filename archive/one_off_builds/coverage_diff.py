import csv

with open("out/targets_with_population.csv", encoding="utf-8") as f:
    targets = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("../ibew-prep/sparky_coverage_117.csv", encoding="utf-8") as f:
    sparky = {r["local_number"]: r for r in csv.DictReader(f)}

with open("out/locals.csv", encoding="utf-8") as f:
    all_locals = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
    olms = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/trade_classes.csv", encoding="utf-8") as f:
    trade_rows = list(csv.DictReader(f))
trade_by_lu = {}
for r in trade_rows:
    trade_by_lu.setdefault(r["lu_number"], []).append(r.get("trade_class_code", ""))

target_lus = set(targets.keys())
sparky_lus = set(sparky.keys())

covered = target_lus & sparky_lus
not_covered = target_lus - sparky_lus
sparky_not_mine = sparky_lus - target_lus

print(f"=== COVERAGE OF MY 245 ===")
print(f"Covered by sparky: {len(covered)}")
print(f"Not covered by sparky: {len(not_covered)}")

def pop(lu):
    v = targets.get(lu, {}).get("population_current_served_inside", "")
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

covered_pop = sum(pop(lu) for lu in covered)
not_covered_pop = sum(pop(lu) for lu in not_covered)
print(f"\nTotal weighted population - covered set: {covered_pop:,.0f}")
print(f"Total weighted population - uncovered set: {not_covered_pop:,.0f}")

print(f"\n=== 25 HIGHEST-POPULATION LOCALS NOT COVERED BY SPARKY ===")
not_covered_sorted = sorted(not_covered, key=pop, reverse=True)
for lu in not_covered_sorted[:25]:
    t = targets[lu]
    print(f"  LU {lu:>5}  {t['charter_city']}, {t['charter_state']:<3}  pop={pop(lu):>12,.0f}  website={t['website']}")

print(f"\n=== SPARKY LOCALS NOT IN MY 245 (why missing) ===")
for lu in sorted(sparky_not_mine, key=lambda x: int(x) if x.isdigit() else 0):
    s = sparky[lu]
    loc = all_locals.get(lu)
    o = olms.get(lu)
    reasons = []
    if loc is None:
        reasons.append("not found in directory harvest at all")
    else:
        website = (o.get("website") if o else loc.get("website", "")) or ""
        classes = trade_by_lu.get(lu, [])
        state = (o.get("charter_state") if o else loc.get("charter_state", "")) or ""
        if not website.strip():
            reasons.append("no website")
        if classes and "i" not in [c.strip().lower() for c in classes]:
            reasons.append(f"trade class(es)={classes}, no 'i' (inside)")
        elif not classes:
            reasons.append("no trade class data found")
        # crude non-US check: Canadian province codes
        CA_PROVS = {"ON","QC","BC","AB","MB","SK","NS","NB","NL","PE","NT","YT","NU"}
        if state.strip().upper() in CA_PROVS:
            reasons.append(f"non-US (state={state})")
    if not reasons:
        reasons.append("UNKNOWN - present, has website, has 'i' class, appears eligible; investigate")
    print(f"  LU {lu:>5}  {s['city']}, {s['state']:<3}  status={s['sparky_status']!r}  -> {'; '.join(reasons)}")
