"""Reconcile cached Davis-Bacon electrical rates to the 244 target locals.

There are two intentionally independent joins: an ELEC code match (strongest)
and a county-name match against inside jurisdiction rows.  This script never
uses the network and only sends union building rates to the display path.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


OUT = Path("out/local_wage_davisbacon.csv")
DISAGREEMENTS = Path("out/davisbacon_join_disagreements.csv")
APPRENTICE_AUDIT = Path("out/davisbacon_apprentice_comparison.csv")
COVERAGE_ANALYSIS = Path("out/davisbacon_coverage_analysis.csv")
FIELDS = [
    "local_union_id", "lu_number", "charter_city", "population",
    "journeyman_base_low", "journeyman_base_high", "fringe_low", "fringe_high",
    "total_low", "total_high", "wd_effective_date_newest", "wd_effective_date_oldest",
    "county_match_count", "join_method", "is_union_rate", "wd_numbers", "confidence", "flags",
    "range_basis", "alternate_classifications", "selected_classification_code", "selected_classification_text",
    "apprentice_start_pct", "apprentice_top_pct", "apprentice_start_hourly_low",
    "apprentice_start_hourly_high", "apprentice_pay_is_derived", "scraped_apprentice_hourly",
    "apprentice_comparison", "source_wd_number", "source_wd_modification",
]
STATE_ABBR = {
    "alabama":"AL","arizona":"AZ","arkansas":"AR","california":"CA","colorado":"CO","connecticut":"CT","delaware":"DE","district of columbia":"DC","florida":"FL","georgia":"GA","hawaii":"HI","idaho":"ID","illinois":"IL","indiana":"IN","iowa":"IA","kansas":"KS","kentucky":"KY","louisiana":"LA","maine":"ME","maryland":"MD","massachusetts":"MA","michigan":"MI","minnesota":"MN","mississippi":"MS","missouri":"MO","montana":"MT","nebraska":"NE","nevada":"NV","new hampshire":"NH","new jersey":"NJ","new mexico":"NM","new york":"NY","north carolina":"NC","north dakota":"ND","ohio":"OH","oklahoma":"OK","oregon":"OR","pennsylvania":"PA","rhode island":"RI","south carolina":"SC","south dakota":"SD","tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT","virginia":"VA","washington":"WA","west virginia":"WV","wisconsin":"WI","wyoming":"WY",
}
RIGHT_TO_WORK_STATES = {
    "AL", "AR", "AZ", "FL", "GA", "IA", "ID", "IN", "KS", "KY", "LA", "MI", "MS", "NC",
    "ND", "NE", "OK", "SC", "SD", "TN", "TX", "UT", "VA", "WI", "WV", "WY",
}


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def num(value: str) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else ""


def norm(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in (text or "")).split())


def county_token(text: str) -> str:
    # SAM's document header normally says "Bronx" while jurisdictions says
    # "Bronx County".  Compare the county name, not the civic suffix.
    return re.sub(r"\s+(?:county|parish|borough|city)$", "", norm(text))


def is_building(row: dict) -> bool:
    return "building" in (row.get("construction_type") or "").lower()


def is_electrical(row: dict) -> bool:
    # County matching also needs survey identifiers (SUxx...), which do not
    # carry the ELEC prefix.  The local-code path below remains ELEC-only.
    return "ELECTRIC" in row.get("classification_text", "").upper()


def is_inside_wireman(row: dict) -> bool:
    return row.get("work_classification") == "inside_wireman"


def has_qualifier(row: dict) -> bool:
    """True for contract-size / work-tier alternatives, not geography."""
    return bool(re.search(r"\b(?:CONTRACTS?\s+OF|UNDER\s+\$|OVER\s+\$|LESS\s+THAN\s+\$|MORE\s+THAN\s+\$)\b", row.get("classification_text", ""), re.I))


def is_baseline_electrician(row: dict) -> bool:
    """The baseline must be a classification named Electrician, not a scope note."""
    return bool(re.match(r"^\s*ELECTRICIANS?\b", row.get("classification_text", ""), re.I))


def classification_county_qualifiers(row: dict, counties: list[dict]) -> set[str]:
    """Return local county names explicitly named in a classification scope."""
    text = norm(row.get("classification_text", ""))
    if not re.search(r"\bcount(?:y|ies)\b", text):
        return set()
    # A division name ("Peoria Division") is not itself a county qualifier.
    text = re.sub(r"\b[a-z]+\s+division\s+", "", text)
    state = STATE_ABBR.get((row.get("state") or "").strip().lower(), (row.get("state") or "").strip().upper())
    return {
        county_token(c["name"])
        for c in counties
        if c["state"] == state and re.search(rf"\b{re.escape(county_token(c['name']))}\b", text)
    }


def scoped_rate_rows(rows: list[dict], counties: list[dict], home_county: dict | None) -> list[dict]:
    """Keep only determinations and classification scopes applicable at home."""
    scoped = []
    local_tokens = {county_token(c["name"]) for c in counties}
    home_token = county_token(home_county["name"]) if home_county else ""
    for row in rows:
        # A populated determination header must overlap the local jurisdiction.
        if row.get("counties") and not county_matches(row, counties):
            continue
        qualifiers = classification_county_qualifiers(row, counties)
        if qualifiers:
            allowed = {home_token} if home_token else local_tokens
            if not qualifiers.intersection(allowed):
                continue
        copy = dict(row)
        copy["_county_qualifiers"] = ";".join(sorted(qualifiers))
        scoped.append(copy)
    return scoped


def select_survivors(rows: list[dict]) -> tuple[list[dict], str, list[dict]]:
    """Choose a non-contaminating inside-wireman baseline.

    Geography-only rows can remain a range.  If contract-size tiers survive,
    use the least-qualified non-tier Electrician row rather than blending it
    with higher/lower qualified work.
    """
    if not rows:
        return [], "", []
    baseline = [r for r in rows if is_baseline_electrician(r)]
    plain = [r for r in baseline if not has_qualifier(r)]
    alternatives = [r for r in rows if r not in plain]
    selected = plain or rows
    # Repeated rows are common when the same construction document has mixed
    # types. Deduplicate only literal same-rate/classification copies.
    unique = {}
    for r in selected:
        key = (r.get("wd_number"), r.get("wd_modification"), r.get("classification_code"), r.get("classification_text"), r.get("base_rate"), r.get("fringe_raw"))
        unique[key] = r
    selected = list(unique.values())
    if len(selected) == 1:
        return selected, "single_classification", alternatives
    geography = {
        (norm(r.get("counties", "")), r.get("_county_qualifiers", ""),
         re.search(r"\bzone\s+[a-z0-9]+\b", r.get("classification_text", ""), re.I).group(0).lower()
         if re.search(r"\bzone\s+[a-z0-9]+\b", r.get("classification_text", ""), re.I) else "")
        for r in selected
    }
    return selected, "geographic" if len(geography) > 1 else "same_geography_multiple_classifications", alternatives


def date_key(value: str) -> datetime:
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return datetime.min


def rate_summary(rows: list[dict]) -> dict:
    usable = [r for r in rows if num(r.get("base_rate")) is not None and num(r.get("total_rate")) is not None]
    if not usable:
        return {"rows": [], "base_low": None, "base_high": None, "fringe_low": None, "fringe_high": None,
                "total_low": None, "total_high": None, "dates": [], "wds": []}
    return {
        "rows": usable,
        "base_low": min(num(r["base_rate"]) for r in usable),
        "base_high": max(num(r["base_rate"]) for r in usable),
        "fringe_low": min(num(r["fringe_computed"]) for r in usable),
        "fringe_high": max(num(r["fringe_computed"]) for r in usable),
        "total_low": min(num(r["total_rate"]) for r in usable),
        "total_high": max(num(r["total_rate"]) for r in usable),
        "dates": sorted({r.get("wd_effective_date", "") for r in usable if r.get("wd_effective_date")}, key=date_key),
        "wds": sorted({f'{r.get("wd_number", "")}/{r.get("wd_modification", "")}' for r in usable}),
    }


def midpoint(summary: dict) -> float | None:
    if summary["base_low"] is None:
        return None
    return (summary["base_low"] + summary["base_high"]) / 2


def county_matches(rate: dict, counties: list[dict]) -> int:
    text = norm(rate.get("counties", ""))
    if not text:
        return 0
    state = STATE_ABBR.get((rate.get("state") or "").strip().lower(), (rate.get("state") or "").strip().upper())
    # Statewide determinations have no finite county list; they apply to all
    # inside counties in that state.
    if "statewide" in text or "all counties" in text:
        return sum(1 for c in counties if c["state"] == state)
    return sum(1 for c in counties if c["state"] == state and county_token(c["name"]) in text)


def home_counties_by_lu(counties_by_lu: dict[str, list[dict]]) -> dict[str, dict]:
    """Resolve a local's headquarters ZIP to one of its inside counties."""
    zip_fips: dict[str, set[str]] = defaultdict(set)
    for row in load("hud/zip_county.csv"):
        if row.get("zip") and row.get("geoid"):
            zip_fips[row["zip"].zfill(5)].add(str(row["geoid"]).zfill(5))
    homes: dict[str, dict] = {}
    for address in load("out/addresses.csv"):
        lu = address.get("lu_number", "")
        for county in counties_by_lu.get(lu, []):
            if county.get("fips") in zip_fips.get((address.get("Zip") or "").zfill(5), set()):
                homes[lu] = county
                break
    return homes


def coverage_verdict(local_code_seen: bool, state_docs: int, state_elec_codes: int,
                     building_rows: list[dict], building_electrical: list[dict]) -> str:
    if state_docs < 3:
        return "not_pulled"
    if building_rows and building_electrical and not any(r.get("is_union_rate") == "true" for r in building_electrical):
        return "no_union_rate_published"
    if not local_code_seen and state_elec_codes:
        return "local_code_absent"
    return "not_pulled"


def main() -> None:
    rates = load("out/davisbacon_rates.csv")
    targets = load("out/targets_with_population.csv")
    reconciled = {r["lu_number"]: r for r in load("out/wage_reconciled.csv")}
    counties_by_lu: dict[str, list[dict]] = defaultdict(list)
    for r in load("out/jurisdictions.csv"):
        if (r.get("jurisdiction_type") or "").strip().upper() == "I":
            counties_by_lu[r["lu_number"]].append({
                "state": (r.get("state_province") or "").upper(),
                "name": r.get("census_match_name") or r.get("county_name") or "",
                "fips": (r.get("census_fips") or "").zfill(5),
            })
    home_by_lu = home_counties_by_lu(counties_by_lu)

    display_pool = [r for r in rates if is_building(r) and is_electrical(r) and is_inside_wireman(r) and not r.get("flags")]
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in display_pool:
        if r.get("is_union_rate") == "true" and r.get("local_number_from_code"):
            by_code[r["local_number_from_code"]].append(r)
    all_code_locals = {r.get("local_number_from_code") for r in rates if r.get("local_number_from_code")}

    output, disagreements, apprentice_rows = [], [], []
    for target in targets:
        lu = target["lu_number"]
        local_counties = counties_by_lu.get(lu, [])
        home_county = home_by_lu.get(lu)
        code_rows, code_basis, code_alternatives = select_survivors(scoped_rate_rows(by_code.get(lu, []), local_counties, home_county))
        county_rows = scoped_rate_rows([r for r in display_pool if county_matches(r, local_counties)], local_counties, home_county)
        county_union_input = [r for r in county_rows if r.get("is_union_rate") == "true"]
        # When this local's own ELEC code exists but has no home-county
        # survivor, do not substitute a neighbouring local's rate by county.
        if lu in all_code_locals and not code_rows:
            county_union_input = []
        county_union, county_basis, county_alternatives = select_survivors(county_union_input)
        county_survey = [r for r in county_rows if r.get("is_union_rate") != "true"]
        code_summary, county_summary = rate_summary(code_rows), rate_summary(county_union)
        chosen = code_summary if code_summary["rows"] else county_summary
        range_basis = code_basis if code_summary["rows"] else county_basis
        alternatives = code_alternatives if code_summary["rows"] else county_alternatives
        join_method = "both" if code_summary["rows"] and county_summary["rows"] else ("local_code" if code_summary["rows"] else ("county" if county_summary["rows"] else ""))
        flags: list[str] = []
        cmid, dmid = midpoint(code_summary), midpoint(county_summary)
        if cmid and dmid and abs(cmid - dmid) / cmid > .10:
            flags.append("local_code_county_base_disagree_over_10pct")
            disagreements.append({"lu_number": lu, "charter_city": target["charter_city"], "local_code_base_low": fmt(code_summary["base_low"]), "local_code_base_high": fmt(code_summary["base_high"]), "county_base_low": fmt(county_summary["base_low"]), "county_base_high": fmt(county_summary["base_high"]), "preferred": "local_code"})
        if chosen["rows"]:
            if chosen["base_low"] < 22 or chosen["base_high"] > 95:
                flags.append("base_outside_plausibility_band")
            if chosen["total_low"] < 30 or chosen["total_high"] > 150:
                flags.append("total_outside_plausibility_band")
            if chosen["base_high"] / chosen["base_low"] > 1.3:
                flags.append("inside_wireman_base_range_over_1_3x")
        survey_only = not chosen["rows"] and bool(county_survey)
        if survey_only:
            flags.append("survey_only_excluded_from_display")
        old = reconciled.get(lu, {})
        pct = num(old.get("apprentice_start_pct", ""))
        top_pct = num(old.get("apprentice_top_pct", ""))
        derive = bool(chosen["rows"] and pct is not None)
        apt_low = chosen["base_low"] * pct / 100 if derive else None
        apt_high = chosen["base_high"] * pct / 100 if derive else None
        scraped = num(old.get("apprentice_start_hourly", ""))
        comparison = ""
        if derive and scraped is not None and apt_low is not None:
            expected = (apt_low + apt_high) / 2
            comparison = "agree_within_15pct" if abs(scraped - expected) <= expected * .15 else "disagree_over_15pct"
            apprentice_rows.append({"lu_number": lu, "charter_city": target["charter_city"], "scraped_apprentice_hourly": fmt(scraped), "derived_low": fmt(apt_low), "derived_high": fmt(apt_high), "pct": fmt(pct), "comparison": comparison})
        source = max(chosen["rows"], key=lambda r: date_key(r.get("wd_effective_date", "")), default={})
        alternate_text = " | ".join(sorted({f'{r.get("classification_code", "")}: {r.get("classification_text", "")}' for r in alternatives}))
        output.append({
            "local_union_id": target["local_union_id"], "lu_number": lu, "charter_city": target["charter_city"],
            "population": target.get("population_current_served_inside", ""),
            "journeyman_base_low": fmt(chosen["base_low"]), "journeyman_base_high": fmt(chosen["base_high"]),
            "fringe_low": fmt(chosen["fringe_low"]), "fringe_high": fmt(chosen["fringe_high"]),
            "total_low": fmt(chosen["total_low"]), "total_high": fmt(chosen["total_high"]),
            "wd_effective_date_newest": chosen["dates"][-1] if chosen["dates"] else "",
            "wd_effective_date_oldest": chosen["dates"][0] if chosen["dates"] else "",
            "county_match_count": str(sum(county_matches(r, local_counties) for r in county_rows)),
            "join_method": join_method, "is_union_rate": "true" if chosen["rows"] else "false",
            "wd_numbers": ";".join(chosen["wds"]),
            "confidence": "high" if join_method in ("local_code", "both") else ("medium" if join_method == "county" else ("low" if survey_only else "none")),
            "flags": ";".join(flags), "apprentice_start_pct": fmt(pct), "apprentice_top_pct": fmt(top_pct),
            "range_basis": range_basis, "alternate_classifications": alternate_text,
            "selected_classification_code": source.get("classification_code", ""),
            "selected_classification_text": source.get("classification_text", ""),
            "apprentice_start_hourly_low": fmt(apt_low), "apprentice_start_hourly_high": fmt(apt_high),
            "apprentice_pay_is_derived": "true" if derive else "false", "scraped_apprentice_hourly": fmt(scraped),
            "apprentice_comparison": comparison, "source_wd_number": source.get("wd_number", ""),
            "source_wd_modification": source.get("wd_modification", ""),
        })
    coverage_rows = []
    state_docs: dict[str, set[str]] = defaultdict(set)
    state_elec_codes: dict[str, set[str]] = defaultdict(set)
    rates_by_state: dict[str, list[dict]] = defaultdict(list)
    local_codes_seen: set[str] = set()
    for rate in rates:
        state = STATE_ABBR.get((rate.get("state") or "").strip().lower(), (rate.get("state") or "").strip().upper())
        if state:
            rates_by_state[state].append(rate)
            state_docs[state].add(rate.get("wd_number", ""))
            if (rate.get("classification_code") or "").upper().startswith("ELEC"):
                state_elec_codes[state].add(rate["classification_code"])
            if rate.get("local_number_from_code"):
                local_codes_seen.add(rate["local_number_from_code"])
    rendered = {r["lu_number"]: r for r in output}
    for target in targets:
        lu, state = target["lu_number"], target.get("charter_state", "")
        display = rendered[lu]
        if display["is_union_rate"] == "true":
            continue
        local_counties = counties_by_lu.get(lu, [])
        building_rows = [r for r in rates_by_state[state] if is_building(r) and county_matches(r, local_counties)]
        building_electrical = [r for r in building_rows if is_electrical(r)]
        local_code_seen = lu in local_codes_seen
        verdict = coverage_verdict(local_code_seen, len(state_docs[state]), len(state_elec_codes[state]), building_rows, building_electrical)
        coverage_rows.append({
            "local_union_id": target["local_union_id"], "lu_number": lu, "charter_city": target["charter_city"],
            "state": state, "population": target.get("population_current_served_inside", ""),
            "is_right_to_work_state": "true" if state in RIGHT_TO_WORK_STATES else "false",
            "determinations_cached_for_state": str(len(state_docs[state])),
            "elec_codes_seen_in_state": str(len(state_elec_codes[state])),
            "local_code_seen_anywhere": "true" if local_code_seen else "false", "verdict": verdict,
        })
    for path, rows, fields in [
        (OUT, output, FIELDS),
        (DISAGREEMENTS, disagreements, ["lu_number", "charter_city", "local_code_base_low", "local_code_base_high", "county_base_low", "county_base_high", "preferred"]),
        (APPRENTICE_AUDIT, apprentice_rows, ["lu_number", "charter_city", "scraped_apprentice_hourly", "derived_low", "derived_high", "pct", "comparison"]),
        (COVERAGE_ANALYSIS, coverage_rows, ["local_union_id", "lu_number", "charter_city", "state", "population", "is_right_to_work_state", "determinations_cached_for_state", "elec_codes_seen_in_state", "local_code_seen_anywhere", "verdict"]),
    ]:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    union = sum(r["is_union_rate"] == "true" for r in output)
    survey = sum(r["confidence"] == "low" for r in output)
    print(f"locals={len(output)} union={union} survey_only={survey} no_match={len(output)-union-survey}")
    print(f"disagreements_over_10pct={len(disagreements)} derived_apprentice={sum(r['apprentice_pay_is_derived']=='true' for r in output)}")


if __name__ == "__main__":
    main()
