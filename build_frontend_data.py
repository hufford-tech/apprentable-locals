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


def slugify(lu, city, state):
    c = "".join(ch.lower() if ch.isalnum() else "-" for ch in city).strip("-")
    while "--" in c:
        c = c.replace("--", "-")
    return f"ibew-local-{lu}-{c}-{state.lower()}"


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


targets = load("out/targets_with_population.csv")
extraction = {r["lu_number"]: r for r in load("out/extraction_v2.csv")}
olms = {r["local_union_id"]: r for r in load("out/locals_joined_olms.csv")}
zip_rows = load("out/zip_to_local.csv")
jurisdictions = load("out/jurisdictions.csv")

# Task 4 (frontend round): validated contact info, crawled value preferred on
# disagreement with the IBEW directory since it came from the local's own live
# site. See out/contact_validation.csv / build_contact_validation.py.
contact_by_lu = {r["lu_number"]: r for r in load("out/contact_validation.csv")}


def recommended_contact(lu):
    r = contact_by_lu.get(lu)
    if not r:
        return "", ""
    email = r["crawled_email"] if r["email_agreement"] in ("mismatch", "match", "crawled_only") else r["directory_email"]
    phone = r["crawled_phone"] if r["phone_agreement"] in ("mismatch", "match", "crawled_only") else r["directory_phone"]
    return email, phone

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

# Task 6: per-(zip, local) res_ratio/coverage/confidence, aggregated across any
# duplicate rows (a ZIP can straddle multiple counties mapped to the same
# local). Used to build the multi-local comparison view -- a county-level ZIP
# can genuinely fall under more than one local, so surface the raw numbers
# rather than silently picking one.
CONF_RANK = {"high": 3, "medium": 2, "med": 2, "low": 1, "": 0}
zip_local_agg = defaultdict(lambda: defaultdict(lambda: {"res_ratio": 0.0, "county_pct_coverage": 0.0, "confidence": ""}))
for r in zip_rows:
    z = r["zip"].zfill(5)
    lid = r["local_union_id"]
    agg = zip_local_agg[z][lid]
    try:
        agg["res_ratio"] += float(r.get("res_ratio") or 0)
    except ValueError:
        pass
    try:
        agg["county_pct_coverage"] = max(agg["county_pct_coverage"], float(r.get("county_pct_coverage") or 0))
    except ValueError:
        pass
    conf = (r.get("confidence") or "").strip().lower()
    if CONF_RANK.get(conf, 0) >= CONF_RANK.get(agg["confidence"], 0):
        agg["confidence"] = conf

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
        contact_email, contact_phone = recommended_contact(lu)
        jatc = e.get("jatc_name") or e.get("program_name") or ""
        aptitude = e.get("aptitude_test", "")
        min_age = e.get("min_age", "")
        min_edu = e.get("min_education", "")
    else:
        cs = {"computed_status": "unknown", "status_confidence": "low",
              "days_since_evidence": None, "intake_pattern": ""}
        quote = src = app_url = jatc = ""
        contact_email, contact_phone = recommended_contact(lu)
        aptitude = min_age = min_edu = ""

    status_counts[cs["computed_status"]] += 1
    o = olms.get(lid, {})
    cl = sorted(counties.get(lid, []), key=lambda c: -(c["pop"] or 0))

    locals_out.append({
        "id": lid,
        "lu": lu,
        "slug": slugify(lu, t["charter_city"], t["charter_state"]),
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

# Task 6: comparison-view metadata for ZIPs resolving to >1 local. Sorted by
# res_ratio descending so the most likely local is first. Distance from the
# searched ZIP's city is included only when that city matches a charter city
# we have coordinates for (best-effort -- omitted otherwise).
import math


def haversine_mi(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


zip_multi = {}
for z, hits in zip_index.items():
    if len(hits) < 2:
        continue
    zip_coords = CITY_COORDS.get(zip_city.get(z, (None, None)))
    cands = []
    for n in hits:
        lid = locals_out[n]["id"]
        agg = zip_local_agg.get(z, {}).get(lid, {"res_ratio": 0.0, "county_pct_coverage": 0.0, "confidence": ""})
        dist = None
        if zip_coords:
            dist = round(haversine_mi(zip_coords[0], zip_coords[1], locals_out[n]["lat"], locals_out[n]["lon"]), 1)
        cands.append({
            "i": n,
            "r": round(agg["res_ratio"], 3),
            "c": round(agg["county_pct_coverage"], 1),
            "cf": agg["confidence"][:1],  # h/m/l/''
            "d": dist,
        })
    cands.sort(key=lambda c: -c["r"])
    zip_multi[z] = cands

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
    "zip_multi": {z: h for z, h in sorted(zip_multi.items())},
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
print(f"zips with >1 local (comparison view): {len(zip_multi):,}")
print(f"cities indexed: {len(city_index):,}")
print(f"status: {dict(sorted(status_counts.items(), key=lambda x: -x[1]))}")
import os
print(f"bundle size: {os.path.getsize('out/frontend_data.json')/1024:.0f} KB")
