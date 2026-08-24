import csv
import datetime
import json
import pickle

from scrape_lib2 import call_extraction

CACHE_PATH = "raw/dry_run3_cache.pkl"
JATC_CACHE_PATH = "raw/dry_run3_jatc_cache.pkl"
CURRENT_YEAR = datetime.date.today().year

with open(CACHE_PATH, "rb") as f:
    local_results = pickle.load(f)
with open(JATC_CACHE_PATH, "rb") as f:
    jatc_pages_by_domain = pickle.load(f)

with open("../ibew-prep/sparky_coverage_117.csv", encoding="utf-8") as f:
    sparky = {r["local_number"]: r["sparky_status"] for r in csv.DictReader(f)}

results = {}
for lu, r in local_results.items():
    t = r["target"]
    pages = list(r["pages_collected"])
    for dom in r["external_domains"]:
        pages.extend(jatc_pages_by_domain.get(dom, []))

    extracted, usage = call_extraction(
        lu, t["charter_city"], pages,
        current_year=CURRENT_YEAR,
        website_corrected=False, original_website=t["website"], state_dol_url="",
    )
    results[lu] = extracted

with open("out/dry_run_extraction_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"{'LU':>5}  {'my accepting_applications':<28} {'sparky_status':<20} agree?")
for lu, ex in results.items():
    mine = ex.get("accepting_applications", "unknown")
    theirs = sparky.get(lu, "MISSING")
    print(f"{lu:>5}  {str(mine):<28} {theirs:<20}")
