"""Build out/frontend_data.json for ibew_finder.html.

Joins the 245 class-i scrape targets to computed status, OLMS membership,
served population, jurisdiction counties, and the ZIP index. Emits one compact
JSON blob that gets inlined into the single-file page.

Zero network, zero API cost. Read-only against out/*.csv.
"""
import csv
import json
import sys
import os
from datetime import date, datetime
from collections import Counter, defaultdict
from statistics import mean

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


def clean_optional(value):
    """Keep source files unchanged, but stop sentinel strings at the build boundary."""
    value = "" if value is None else str(value).strip()
    return "" if value in {"False", "True", "None", "nan"} else value


# Task: aptitude_test sometimes captured where the scraper found something
# ("referenced via GAN Study Guide link") rather than what the test actually
# is. That tells a candidate nothing and looks like an internal note leaking
# onto the page -- blank it rather than ship a scraper artifact as a fact.
APTITUDE_ARTIFACT_MARKERS = ("referenced via", "study guide link", "practice test linked")


def clean_aptitude(value):
    v = clean_optional(value)
    if v and any(m in v.lower() for m in APTITUDE_ARTIFACT_MARKERS):
        return ""
    return v


def wage_source_url(source_file):
    try:
        with open(source_file, encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
        return first if first.startswith(("http://", "https://")) else ""
    except OSError:
        return ""


targets = load("out/targets_with_population.csv")
extraction = {r["lu_number"]: r for r in load("out/extraction_v2.csv")}
olms = {r["local_union_id"]: r for r in load("out/locals_joined_olms.csv")}
zip_rows = load("out/zip_to_local.csv")
jurisdictions = load("out/jurisdictions.csv")
# Davis-Bacon remains the journeyman source. Apprentice pay has its own source
# precedence below: a reviewed local-published schedule, RAPIDS registration
# wages, then a Davis-Bacon-derived percentage where one already exists.
davisbacon_wages = {}
if os.path.exists("out/local_wage_davisbacon.csv"):
    for r in load("out/local_wage_davisbacon.csv"):
        # LU 8 Toledo carries base=$13.02, which the wage pipeline already
        # flags as base_outside_plausibility_band -- it was being displayed
        # anyway. A flagged rate is not publishable as a journeyman scale.
        implausible = "plausibility" in (r.get("flags") or "")
        if (r.get("is_union_rate") == "true" and r.get("confidence") in {"high", "medium"}
                and r.get("journeyman_base_low") and not implausible):
            davisbacon_wages[r["lu_number"]] = r

published_apprentice_wages = {}
if os.path.exists("out/wage_reconciled.csv"):
    for r in load("out/wage_reconciled.csv"):
        # Only the existing display tier is trusted as a local-published
        # schedule. Review/reject rows remain audit material until validated.
        if r.get("tier") == "display" and r.get("apprentice_start_hourly"):
            source_file = r.get("source_file", "")
            published_apprentice_wages[r["lu_number"]] = {
                "kind": "jatc_published",
                "start_hourly_low": r["apprentice_start_hourly"],
                "start_hourly_high": r["apprentice_start_hourly"],
                "start_pct": r.get("apprentice_start_pct", ""),
                "top_pct": r.get("apprentice_top_pct", ""),
                "effective_date": r.get("effective_date", ""),
                "effective_precision": r.get("effective_date_precision", ""),
                "source": wage_source_url(source_file),
                "source_label": "Local-published apprenticeship wage schedule",
                "program_names": "",
                "record_count": "",
            }

rapids_apprentice_wages = {}
if os.path.exists("out/rapids_apprentice_wages.csv"):
    for r in load("out/rapids_apprentice_wages.csv"):
        rapids_apprentice_wages[r["lu_number"]] = r

# National fallback benchmark. It is the arithmetic mean of the available
# local-level apprentice medians/start rates, never a Davis-Bacon journeyman
# average. Keep the sample size in the payload so the UI can explain exactly
# what the number is (and what it is not).
displayable_lus = {
    t["lu_number"] for t in targets
    if float(t.get("population_current_served_inside") or 0) > 0
}
benchmark_values = {}
for lu, r in rapids_apprentice_wages.items():
    if lu in displayable_lus and r.get("apprentice_start_hourly_median"):
        benchmark_values[lu] = float(r["apprentice_start_hourly_median"])
for lu, r in published_apprentice_wages.items():
    if lu in displayable_lus and r.get("start_hourly_low"):
        benchmark_values[lu] = float(r["start_hourly_low"])
national_apprentice_average = mean(benchmark_values.values()) if benchmark_values else None
national_apprentice_wage = {
    "kind": "national_average",
    "start_hourly_low": f"{national_apprentice_average:.2f}" if national_apprentice_average is not None else "",
    "start_hourly_high": f"{national_apprentice_average:.2f}" if national_apprentice_average is not None else "",
    "effective_date": "2026-08-17",
    "source": "https://www.apprenticeship.gov/help/what-rapids",
    "source_label": "National apprentice-wage benchmark",
    "sample_local_count": str(len(benchmark_values)),
}
recovered_apps = {}
if os.path.exists("out/application_url_candidates.csv"):
    for r in load("out/application_url_candidates.csv"):
        if r.get("chosen", "").lower() == "true" and r.get("candidate_url"):
            recovered_apps[r["lu_number"]] = r["candidate_url"]

# RAPIDS KPI (Active/New Apprentices, DOL's own formulas) -- see
# rapids_kpi_join_locals.py. Round 2: this full detail block (Active +
# New apprentices, with period) is restricted to name-matched locals only.
# A city-matched program is a real program serving roughly that market, which
# is enough for the peer-based intake estimate below, but it is NOT confirmed
# to be that specific local's own program -- showing its raw Active-apprentice
# count as if it were that local's own number is exactly the failure mode
# that got RAPIDS_DISPLAY turned off last round. Behind RAPIDS_DISPLAY in the
# template.
rapids_kpi = {}
if os.path.exists("out/rapids_kpi_by_lu.csv"):
    for r in load("out/rapids_kpi_by_lu.csv"):
        if r.get("match_type") == "lu_number_match":
            rapids_kpi[r["lu_number"]] = r

# Peer-based estimated annual intake (out/rapids_intake_estimate_by_lu.csv,
# rapids_intake_estimate.py) -- confirmed tier for the 58 name-matched locals
# (their own reported figure), estimated tier (bin median, rounded) for every
# other local with a jurisdiction population, not_published otherwise.
intake_by_lu = {}
if os.path.exists("out/rapids_intake_estimate_by_lu.csv"):
    for r in load("out/rapids_intake_estimate_by_lu.csv"):
        intake_by_lu[r["lu_number"]] = r

monitor_days = {}
if os.path.exists("out/monitor_state.json"):
    with open("out/monitor_state.json", encoding="utf-8") as f:
        monitor_state = json.load(f)
    today = date.today()
    for local_id, record in monitor_state.items():
        stamp = record.get("last_changed")
        if not stamp:
            monitor_days[local_id] = None
            continue
        try:
            changed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
            monitor_days[local_id] = max(0, (today - changed).days)
        except (TypeError, ValueError):
            monitor_days[local_id] = None


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
tier_counts = defaultdict(Counter)

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
        app_url = clean_optional(e.get("application_url", ""))
        app_url_recovered = False
        if not app_url and lu in recovered_apps:
            app_url = recovered_apps[lu]
            app_url_recovered = True
        contact_email, contact_phone = recommended_contact(lu)
        jatc = clean_optional(e.get("jatc_name")) or clean_optional(e.get("program_name"))
        aptitude = clean_aptitude(e.get("aptitude_test", ""))
        min_age = clean_optional(e.get("min_age", ""))
        min_edu = clean_optional(e.get("min_education", ""))
    else:
        cs = {"computed_status": "unknown", "status_confidence": "low",
              "days_since_evidence": None, "intake_pattern": ""}
        quote = src = app_url = jatc = ""
        app_url_recovered = False
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
        "website": clean_optional(t.get("website", "")),
        "jatc": jatc,
        "status": cs["computed_status"],
        "conf": cs["status_confidence"],
        "pattern": cs.get("intake_pattern", "") or "",
        "next_open": cs.get("next_open_date", "") or "",
        "next_close": cs.get("next_close_date", "") or "",
        "days_since": cs["days_since_evidence"],
        "quote": quote,
        "src": src,
        "app_url": app_url,
        "app_url_recovered": app_url_recovered,
        "monitor_days_since_change": monitor_days.get(lid),
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
    kpi = rapids_kpi.get(lu)
    if kpi:
        locals_out[-1]["rapids_kpi"] = {
            "active": int(float(kpi["active_apprentices"])),
            "new": int(float(kpi["new_apprentices"])),
            "period_start": kpi["period_start"],
            "period_end": kpi["period_end"],
            "prog_name": kpi.get("prog_name", ""),
        }

    intake = intake_by_lu.get(lu)
    if intake and intake.get("tier") in ("confirmed", "estimated"):
        locals_out[-1]["intake"] = {
            "tier": intake["tier"],
            "value": int(float(intake["value"])),
            "period_start": intake["period_start"],
            "period_end": intake["period_end"],
        }
    locals_out[-1]["intake_tier"] = intake["tier"] if intake else "not_published"
    tier_counts["intake_tier"][locals_out[-1]["intake_tier"]] += 1

    wage = davisbacon_wages.get(lu)
    if wage:
        wd_number = wage.get("source_wd_number", "")
        wd_revision = wage.get("source_wd_modification", "")
        locals_out[-1]["wage"] = {
            "kind": "davis_bacon",
            "start_hourly_low": wage.get("apprentice_start_hourly_low", ""),
            "start_hourly_high": wage.get("apprentice_start_hourly_high", ""),
            "start_pct": wage.get("apprentice_start_pct", ""),
            "top_pct": wage.get("apprentice_top_pct", ""),
            "base_low": wage.get("journeyman_base_low", ""),
            "base_high": wage.get("journeyman_base_high", ""),
            "fringe_low": wage.get("fringe_low", ""),
            "fringe_high": wage.get("fringe_high", ""),
            "total_low": wage.get("total_low", ""),
            "total_high": wage.get("total_high", ""),
            "effective_date": wage.get("wd_effective_date_newest", ""),
            "wd_number": wd_number,
            "wd_modification": wd_revision,
            "source": f"https://sam.gov/wage-determination/{wd_number}/{wd_revision}" if wd_number and wd_revision else "",
            "classification_code": wage.get("selected_classification_code", ""),
            "classification_text": wage.get("selected_classification_text", ""),
            "apprentice_pay_is_derived": wage.get("apprentice_pay_is_derived") == "true",
        }

    # Source precedence for the candidate-facing apprentice figure. This is
    # deliberately separate from the journeyman wage object because RAPIDS is
    # a registration-time observation, not a current CBA scale.
    apprentice = published_apprentice_wages.get(lu)
    if apprentice:
        locals_out[-1]["apprentice_wage"] = apprentice
    else:
        rapids = rapids_apprentice_wages.get(lu)
        if rapids:
            locals_out[-1]["apprentice_wage"] = {
                "kind": "rapids_registration",
                "start_hourly_low": rapids.get("apprentice_start_hourly_median", ""),
                "start_hourly_high": rapids.get("apprentice_start_hourly_median", ""),
                "observed_low": rapids.get("apprentice_start_hourly_low", ""),
                "observed_high": rapids.get("apprentice_start_hourly_high", ""),
                "effective_date": rapids.get("data_as_of", ""),
                "source": rapids.get("source_url", ""),
                "source_label": "DOL RAPIDS registration-time wage",
                "program_names": rapids.get("program_names", ""),
                "record_count": rapids.get("valid_wage_records", ""),
            }
        elif wage and wage.get("apprentice_pay_is_derived") and wage.get("apprentice_start_hourly_low"):
            locals_out[-1]["apprentice_wage"] = {
                "kind": "davis_bacon_derived",
                "start_hourly_low": wage.get("apprentice_start_hourly_low", ""),
                "start_hourly_high": wage.get("apprentice_start_hourly_high", ""),
                "start_pct": wage.get("apprentice_start_pct", ""),
                "top_pct": wage.get("apprentice_top_pct", ""),
                "effective_date": wage.get("effective_date", ""),
                "source": wage.get("source", ""),
                "source_label": "Davis-Bacon-derived apprentice estimate",
                "program_names": "",
                "record_count": "",
            }
    if "apprentice_wage" not in locals_out[-1] and national_apprentice_average is not None:
        locals_out[-1]["apprentice_wage"] = national_apprentice_wage

    # Task 8: every displayed value carries a tier, as a field rather than
    # implied by copy -- confirmed / national_fallback / not_published.
    # (estimated arrives with the peer-based intake model next round.)
    locals_out[-1]["wage_tier"] = "confirmed" if locals_out[-1].get("wage") else "not_published"
    aw = locals_out[-1].get("apprentice_wage")
    locals_out[-1]["apprentice_wage_tier"] = (
        "not_published" if not aw
        else "national_fallback" if aw.get("kind") == "national_average"
        else "confirmed"
    )
    locals_out[-1]["window_tier"] = (
        "confirmed" if locals_out[-1].get("status") not in (None, "", "unknown") else "not_published"
    )
    for field in ("wage_tier", "apprentice_wage_tier", "window_tier"):
        tier_counts[field][locals_out[-1][field]] += 1

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
    # Baked counts. The --lean build strips the indexes above and fetches them
    # on first search, so the page cannot derive these at boot from the objects.
    "build": __import__("datetime").datetime.now().strftime("%H%M"),
    "zip_count": len(zip_index),
    "city_count": len(city_index),
}

if os.path.exists("out/rapids_intake_meta.json"):
    with open("out/rapids_intake_meta.json", encoding="utf-8") as f:
        bundle["intake_meta"] = json.load(f)

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
print()
print(f"Coverage summary (provenance tier by field, of {len(locals_out)} locals):")
for field in sorted(tier_counts):
    counts = tier_counts[field]
    parts = ", ".join(f"{tier}={counts[tier]}" for tier in ("confirmed", "estimated", "national_fallback", "not_published") if counts[tier])
    print(f"  {field}: {parts}")
import os
print(f"bundle size: {os.path.getsize('out/frontend_data.json')/1024:.0f} KB")
