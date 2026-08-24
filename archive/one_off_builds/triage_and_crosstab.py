import csv
import json

with open("out/extraction_pass2only.csv", encoding="utf-8") as f:
    extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/scrape_targets.csv", encoding="utf-8") as f:
    target_lus = [r["lu_number"] for r in csv.DictReader(f)]

with open("out/local_crawl_state.json", encoding="utf-8") as f:
    local_state = json.load(f)

with open("out/targets_with_population.csv", encoding="utf-8") as f:
    pop = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("../ibew-prep/sparky_coverage_117.csv", encoding="utf-8") as f:
    sparky = {r["local_number"]: r["sparky_status"] for r in csv.DictReader(f)}

# ---- TRIAGE ----
complete, partial, empty = [], [], []
for lu in target_lus:
    r = extraction.get(lu)
    if r is None:
        empty.append(lu)
        continue
    has_url = bool((r.get("application_url") or "").strip())
    accepting = r.get("accepting_applications", "unknown")
    has_status = accepting not in ("unknown", "", None)
    if has_url and has_status:
        complete.append(lu)
    elif has_url or has_status:
        partial.append(lu)
    else:
        empty.append(lu)

print("=== TRIAGE (245 targets) ===")
print(f"COMPLETE: {len(complete)}")
print(f"PARTIAL:  {len(partial)}")
print(f"EMPTY:    {len(empty)}")
print(f"(total: {len(complete)+len(partial)+len(empty)})")

# ---- Domains needed by PARTIAL + EMPTY, prioritized by max population ----
needy = set(partial) | set(empty)


def population(lu):
    v = pop.get(lu, {}).get("population_current_served_inside", "")
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


domain_max_pop = {}
domain_locals = {}
for lu in needy:
    doms = local_state.get(lu, {}).get("external_domains", {})
    p = population(lu)
    for dom in doms:
        domain_locals.setdefault(dom, []).append(lu)
        domain_max_pop[dom] = max(domain_max_pop.get(dom, 0), p)

ordered_domains = sorted(domain_max_pop.keys(), key=lambda d: domain_max_pop[d], reverse=True)
print(f"\n=== DOMAINS NEEDED BY PARTIAL+EMPTY ONLY ({len(ordered_domains)} distinct) ===")
for dom in ordered_domains:
    lus = domain_locals[dom]
    print(f"  {dom:<40} max_pop={domain_max_pop[dom]:>12,.0f}  needed_by_LU={lus}")

# ---- SPARKY CROSS-TAB ----
overlap = [lu for lu in extraction if lu in sparky]
print(f"\n=== SPARKY CROSS-TAB ({len(overlap)} overlapping locals) ===")


def agrees(mine, theirs):
    theirs_l = (theirs or "").strip().lower()
    if mine == "unknown":
        return False
    if mine == "yes":
        return theirs_l != "closed"
    if mine == "no":
        return theirs_l == "closed"
    return False


agree_count = 0
disagree = []
deficit = []  # mine unknown, theirs known
for lu in overlap:
    mine = extraction[lu].get("accepting_applications", "unknown")
    theirs = sparky[lu]
    if agrees(mine, theirs):
        agree_count += 1
    else:
        disagree.append((lu, mine, theirs))
    if mine == "unknown":
        deficit.append((lu, theirs))

print(f"Agreement: {agree_count}/{len(overlap)} = {100*agree_count/len(overlap):.1f}%")
print(f"Coverage deficit (mine=unknown, theirs=known status): {len(deficit)} exact")
for lu, theirs in deficit:
    print(f"  LU {lu}: sparky_status={theirs!r}")

print(f"\nAll disagreements ({len(disagree)}):")
for lu, mine, theirs in disagree:
    print(f"  LU {lu}: mine={mine!r} sparky={theirs!r}")
