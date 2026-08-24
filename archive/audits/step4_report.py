# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/step4_report.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

import csv
import json
from collections import Counter

from compute_status import compute_status

with open("out/extraction_v2.csv", encoding="utf-8") as f:
    extraction = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/scrape_targets.csv", encoding="utf-8") as f:
    target_lus = [r["lu_number"] for r in csv.DictReader(f)]

with open("out/targets_with_population.csv", encoding="utf-8") as f:
    pop = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/local_crawl_state.json", encoding="utf-8") as f:
    local_state = json.load(f)

with open("out/jatc_crawl_state.json", encoding="utf-8") as f:
    jatc_state = json.load(f)

with open("../ibew-prep/sparky_coverage_117.csv", encoding="utf-8") as f:
    sparky = {r["local_number"]: r["sparky_status"] for r in csv.DictReader(f)}

# ---- STEP 4.1: compute_status for every row ----
computed = {}
for lu, r in extraction.items():
    windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
    statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
    record = {"windows": windows, "status_statements": statements,
              "page_last_updated": r.get("page_last_updated") or None}
    result = compute_status(record)
    computed[lu] = result

with open("out/computed_status.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["lu_number", "application_url", "confidence", "computed_status", "status_confidence", "days_since_evidence"])
    for lu, r in extraction.items():
        c = computed[lu]
        w.writerow([lu, r.get("application_url", ""), r.get("confidence", ""),
                    c["computed_status"], c["status_confidence"], c["days_since_evidence"]])
print("Wrote out/computed_status.csv")

# ---- STEP 4.2: TRIAGE ----
complete, partial, empty = [], [], []
for lu in target_lus:
    r = extraction.get(lu)
    if r is None:
        empty.append(lu)
        continue
    has_url = bool((r.get("application_url") or "").strip())
    cs = computed[lu]["computed_status"]
    has_status = cs != "unknown"
    if has_url and has_status:
        complete.append(lu)
    elif has_url or has_status:
        partial.append(lu)
    else:
        empty.append(lu)

print(f"\n=== TRIAGE (245 targets) ===")
print(f"COMPLETE: {len(complete)}")
print(f"PARTIAL:  {len(partial)}")
print(f"EMPTY:    {len(empty)}")

# ---- STEP 4.3: computed_status distribution ----
dist = Counter()
for lu in target_lus:
    if lu in computed:
        dist[computed[lu]["computed_status"]] += 1
    else:
        dist["no_extraction"] += 1
print(f"\n=== computed_status DISTRIBUTION (245) ===")
for k, v in dist.most_common():
    print(f"  {k}: {v}")

# ---- STEP 4.4: SPARKY CROSS-TAB ----
overlap = [lu for lu in extraction if lu in sparky]
print(f"\n=== SPARKY CROSS-TAB ({len(overlap)} overlapping locals) ===")
deficit = [lu for lu in overlap if computed[lu]["computed_status"] == "unknown" and sparky[lu].strip()]
print(f"Coverage deficit (computed_status=unknown, sparky has a real status): {len(deficit)} exact")

qual = Counter()
for lu in overlap:
    cs = computed[lu]["computed_status"]
    sp = sparky[lu].strip().lower()
    if cs in ("rolling", "open") and sp in ("always accepting", "open now"):
        qual["rolling/open <-> accepting-ish sparky"] += 1
    elif cs in ("closed", "closed_pending", "expired_data") and sp == "closed":
        qual["closed-ish <-> Closed sparky"] += 1
    elif cs == "expected_open" and sp in ("window scheduled", "watching"):
        qual["expected_open <-> scheduled/watching sparky"] += 1
    elif cs == "unknown":
        qual["unknown (deficit)"] += 1
    else:
        qual["other mismatch"] += 1
print("Qualitative agreement buckets:")
for k, v in qual.most_common():
    print(f"  {k}: {v}")

# ---- STEP 5: FULL 9-ITEM REPORT ----
print(f"\n{'='*70}\nFULL 9-ITEM REPORT\n{'='*70}")

# 4. has_apprenticeship / application_url, window precision breakdown
has_appr = sum(1 for r in extraction.values() if str(r.get("has_apprenticeship", "")).lower() == "true")
has_url = sum(1 for r in extraction.values() if (r.get("application_url") or "").strip())
precision_counts = Counter()
multi_window = 0
for r in extraction.values():
    windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
    if len(windows) > 1:
        multi_window += 1
    for w in windows:
        precision_counts[w.get("precision", "?")] += 1

print(f"(4) has_apprenticeship: {has_appr}/242   has application_url: {has_url}/242")
print(f"    window precision breakdown: {dict(precision_counts)}")
print(f"(5) locals with >1 window: {multi_window}")

# 6. distinct JATC domains + locals-per-domain distribution
domain_locals = {}
for lu, v in local_state.items():
    for dom in v.get("external_domains", {}):
        domain_locals.setdefault(dom, set()).add(lu)
locals_per_domain = Counter(len(lus) for lus in domain_locals.values())
print(f"(6) distinct JATC/external domains discovered: {len(domain_locals)}   crawled (in jatc_state): {len(jatc_state)}")
print(f"    locals-per-domain distribution: {dict(sorted(locals_per_domain.items()))}")

# 7. zero-yield domains
zero_yield = [d for d, v in jatc_state.items() if not v.get("pages")]
print(f"(7) zero-yield domains: {len(zero_yield)}: {zero_yield}")

# 8. is_stale + oldest content_year
stale_counts = Counter(str(r.get("is_stale", "")).lower() for r in extraction.values())
years = [(int(r["content_year"]), lu) for lu, r in extraction.items() if r.get("content_year") not in ("", None)]
years.sort()
print(f"(8) is_stale counts: {dict(stale_counts)}")
print(f"    ten oldest content_year: {years[:10]}")

# 9. locals with no application_url, sorted by population desc
def population(lu):
    v = pop.get(lu, {}).get("population_current_served_inside", "")
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

no_url = [lu for lu in target_lus if not (extraction.get(lu, {}).get("application_url") or "").strip()]
no_url_sorted = sorted(no_url, key=population, reverse=True)
print(f"(9) locals with no application_url: {len(no_url)} total")
print("    top 25 by population:")
for lu in no_url_sorted[:25]:
    t = pop.get(lu, {})
    print(f"      LU {lu:>5}  {t.get('charter_city','?')}, {t.get('charter_state','?'):<3}  pop={population(lu):>12,.0f}")
