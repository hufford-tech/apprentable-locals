"""Build out/frontend_data.json for ibew_finder.html.

Joins the 245 class-i scrape targets to computed status, OLMS membership,
served population, jurisdiction counties, and the ZIP index. Emits one compact
JSON blob that gets inlined into the single-file page.

Zero network, zero API cost. Read-only against out/*.csv.
"""
import csv
import json
import sys
from collections import defaultdict

from compute_status import compute_status
from city_coords import CITY_COORDS

csv.field_size_limit(10_000_000)


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


targets = load("out/targets_with_population.csv")
extraction = {r["lu_number"]: r for r in load("out/extraction_v2.csv")}
olms = {r["local_union_id"]: r for r in load("out/locals_joined_olms.csv")}
zip_rows = load("out/zip_to_local.csv")
jurisdictions = load("out/jurisdictions.csv")

# ---- ZIP -> USPS city name, for the city search box -------------------------
zip_city = {}
with open("hud/zip_county.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        z = r["zip"].zfill(5)
        if z not in zip_city and r.get("city"):
            zip_city[z] = (r["city"].title(), r["state"])

# ---- counties served, inside jurisdiction only ------------------------------
counties = defaultdict(list)
for r in jurisdictions:
    if (r.get("jurisdiction_type") or "").strip().upper() != "I":
        continue
    counties[r["local_union_id"]].append({
        "name": r.get("census_match_name") or r.get("county_name", ""),
        "state": r.get("state_province", ""),
        "pop": int(float(r["population_current"])) if r.get("population_current") else None,
    })

# ---- ZIPs per local ---------------------------------------------------------
zips_by_local = defaultdict(set)
zip_to_locals = defaultdict(set)
for r in zip_rows:
    lid = r["local_union_id"]
    z = r["zip"].zfill(5)
    zips_by_local[lid].add(z)
    zip_to_locals[z].add(lid)

# ---- assemble ---------------------------------------------------------------
locals_out = []
missing_coords = []
status_counts = defaultdict(int)

excluded_no_inside = []
inside_county_counts = defaultdict(int)
for r in jurisdictions:
    if (r.get("jurisdiction_type") or "").strip().upper() == "I":
        inside_county_counts[r["local_union_id"]] += 1

for t in targets:
    lid, lu = t["local_union_id"], t["lu_number"]

    # Task 1 (frontend round): a target with zero inside counties/population
    # is an outside/utility local misclassified as inside-wireman (e.g. LU 111
    # Denver -- trade_classes lists 'i' but every jurisdiction row is type 'O').
    # Never offer these for an inside apprenticeship. See
    # out/target_classification_audit.csv for the full audit.
    inside_pop = int(float(t["population_current_served_inside"] or 0))
    if inside_county_counts.get(lid, 0) == 0 or inside_pop == 0:
        excluded_no_inside.append((lu, t["charter_city"], t["charter_state"], inside_pop))
        continue

    key = (t["charter_city"], t["charter_state"])
    coords = CITY_COORDS.get(key)
    if not coords:
        missing_coords.append(key)
        continue

    e = extraction.get(lu)
    if e:
        rec = {
            "windows": json.loads(e["windows_json"]) if e.get("windows_json") else [],
            "status_statements": json.loads(e["status_statements_json"]) if e.get("status_statements_json") else [],
            "page_last_updated": e.get("page_last_updated") or None,
        }
        cs = compute_status(rec)
        # most decisive piece of evidence, for the "why we think this" line
        quote, src = "", ""
        for s in rec["status_statements"]:
            if s.get("verbatim_text"):
                quote, src = s["verbatim_text"][:300], s.get("source_url", "")
                break
        if not quote:
            for w in rec["windows"]:
                if w.get("evidence_quote"):
                    quote, src = w["evidence_quote"][:300], w.get("source_url", "")
                    break
        app_url = e.get("application_url", "")
        contact_email = e.get("contact_email", "")
        contact_phone = e.get("contact_phone", "")
        jatc = e.get("jatc_name") or e.get("program_name") or ""
        aptitude = e.get("aptitude_test", "")
        min_age = e.get("min_age", "")
        min_edu = e.get("min_education", "")
    else:
        cs = {"computed_status": "unknown", "status_confidence": "low",
              "days_since_evidence": None, "intake_pattern": ""}
        quote = src = app_url = contact_email = contact_phone = jatc = ""
        aptitude = min_age = min_edu = ""

    status_counts[cs["computed_status"]] += 1
    o = olms.get(lid, {})
    cl = sorted(counties.get(lid, []), key=lambda c: -(c["pop"] or 0))

    locals_out.append({
        "id": lid,
        "lu": lu,
        "city": t["charter_city"],
        "st": t["charter_state"],
        "lat": coords[0],
        "lon": coords[1],
        "pop": int(float(t["population_current_served_inside"] or 0)),
        "rank": int(float(t["rank_current"])) if t.get("rank_current") else None,
        "members": int(float(o["olms_members"])) if o.get("olms_members") else None,
        "website": t.get("website", ""),
        "jatc": jatc,
        "status": cs["computed_status"],
        "conf": cs["status_confidence"],
        "pattern": cs.get("intake_pattern", "") or "",
        "next_open": cs.get("next_open_date", "") or "",
        "days_since": cs["days_since_evidence"],
        "quote": quote,
        "src": src,
        "app_url": app_url,
        "email": contact_email,
        "phone": contact_phone,
        "aptitude": aptitude,
        "min_age": min_age,
        "min_edu": min_edu,
        "counties": [f'{c["name"]}, {c["state"]}' for c in cl[:40]],
        "county_n": len(cl),
        "zip_n": len(zips_by_local.get(lid, ())),
        "meets": t.get("meets", ""),
    })

# ---- compact indexes --------------------------------------------------------
# ZIP index only for ZIPs that resolve to a local we are actually showing.
shown = {l["id"] for l in locals_out}
idx_of = {lid: i for i, lid in enumerate(sorted(shown))}
order = {l["id"]: n for n, l in enumerate(locals_out)}

zip_index = {}
for z, lids in zip_to_locals.items():
    hits = sorted(order[l] for l in lids if l in shown)
    if hits:
        zip_index[z] = hits

# City index: "city, ST" -> list of local indexes, derived through ZIPs.
city_index = defaultdict(set)
for z, hits in zip_index.items():
    cs_ = zip_city.get(z)
    if cs_:
        city_index[f"{cs_[0]}, {cs_[1]}"].update(hits)
# every charter city is searchable even if its ZIP is odd
for n, l in enumerate(locals_out):
    city_index[f'{l["city"]}, {l["st"]}'].add(n)

bundle = {
    "generated": __import__("datetime").date.today().isoformat(),
    "locals": locals_out,
    "zips": {z: h for z, h in sorted(zip_index.items())},
    "cities": {k: sorted(v) for k, v in sorted(city_index.items())},
}

with open("out/frontend_data.json", "w", encoding="utf-8") as f:
    json.dump(bundle, f, separators=(",", ":"))

print(f"locals: {len(locals_out)} of {len(targets)} targets")
if excluded_no_inside:
    print(f"EXCLUDED (zero inside county/population) ({len(excluded_no_inside)}):")
    for lu, city, st, pop in excluded_no_inside:
        print(f"    LU {lu}  {city}, {st}  inside_pop={pop}")
if missing_coords:
    print(f"MISSING COORDS ({len(missing_coords)}), dropped from the map:")
    for k in missing_coords:
        print("   ", k)
print(f"zips indexed: {len(zip_index):,}")
print(f"cities indexed: {len(city_index):,}")
print(f"status: {dict(sorted(status_counts.items(), key=lambda x: -x[1]))}")
import os
print(f"bundle size: {os.path.getsize('out/frontend_data.json')/1024:.0f} KB")
