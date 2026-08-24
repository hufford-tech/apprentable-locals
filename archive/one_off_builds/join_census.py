import csv
import re
import unicodedata

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "Puerto Rico": "PR",
}

SUFFIXES = [
    "city and borough", "census area", "borough", "municipality", "parish",
    "county", "division", "area", "city",
]


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def prenormalize(raw):
    # lowercase + accent-fold + st./saint, but keep suffix words intact --
    # this is the form ALIASES keys are written against.
    s = strip_accents(raw).lower().strip()
    s = re.sub(r"^st\.\s+", "saint ", s)
    s = re.sub(r"^st\s+", "saint ", s)
    s = s.replace("st.", "saint")
    s = re.sub(r"[.,]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_name(raw):
    s = prenormalize(raw)
    is_city = False
    changed = True
    while changed:
        changed = False
        for suf in SUFFIXES:
            if s.endswith(" " + suf):
                if suf == "city":
                    is_city = True
                s = s[: -(len(suf) + 1)].strip()
                changed = True
                break
    s = re.sub(r"\s+", " ", s).strip()
    return s, is_city


# ---- Load Census data ----
census_rows = []
with open("census/co-est2024-alldata.csv", encoding="latin-1") as f:
    for r in csv.DictReader(f):
        if r["COUNTY"] == "000":
            continue  # state-level summary row
        state_abbr = STATE_ABBR.get(r["STNAME"])
        if not state_abbr:
            continue
        norm, is_city = normalize_name(r["CTYNAME"])
        census_rows.append({
            "state": state_abbr,
            "raw_name": r["CTYNAME"],
            "norm": norm,
            "is_city": is_city,
            "fips": r["STATE"] + r["COUNTY"],
            "pop2024": int(r["POPESTIMATE2024"]),
        })

exact_index = {}       # (state, norm, is_city) -> record
loose_index = {}        # (state, norm) -> list of records (for fallback / ambiguity detection)
for c in census_rows:
    exact_index[(c["state"], c["norm"], c["is_city"])] = c
    loose_index.setdefault((c["state"], c["norm"]), []).append(c)

# ---- Load IBEW jurisdictions ----
with open("out/jurisdictions.csv", encoding="utf-8") as f:
    j_rows = list(csv.DictReader(f))

CANADIAN = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}


def is_us_row(r):
    return r["state_province"].strip().upper() not in CANADIAN and r["state_province"].strip() != ""


# Known renames / spelling differences between the IBEW directory's legacy
# county names and current Census Bureau names. Only applied where there is
# a clean 1:1 modern successor.
ALIASES = {
    ("AL", "de kalb county"): "dekalb county",
    ("GA", "de kalb county"): "dekalb county",
    ("IL", "de kalb county"): "dekalb county",
    ("IN", "de kalb county"): "dekalb county",
    ("MO", "de kalb county"): "dekalb county",
    ("TN", "de kalb county"): "dekalb county",
    ("FL", "de soto county"): "desoto county",
    ("MS", "de soto county"): "desoto county",
    ("IL", "la salle county"): "lasalle county",
    ("LA", "la salle parish"): "lasalle parish",
    ("IN", "la porte county"): "laporte county",
    ("ND", "la moure county"): "lamoure county",
    ("IL", "du page county"): "dupage county",
    ("TX", "de witt county"): "dewitt county",
    ("IA", "obrien county"): "o'brien county",
    ("MD", "prince georges county"): "prince george's county",
    ("MD", "queen annes county"): "queen anne's county",
    ("MD", "saint marys county"): "saint mary's county",
    ("FL", "dade county"): "miami-dade county",
    ("SD", "shannon county"): "oglala lakota county",
    ("AK", "mantanuska-susitna division"): "matanuska-susitna borough",
    ("AK", "wade hampton area"): "kusilvak census area",
    ("AK", "aleutian islands west"): "aleutians west census area",
    ("AK", "ketchikan division"): "ketchikan gateway borough",
    ("AK", "kodiak division"): "kodiak island borough",
    ("AK", "fairbanks division"): "fairbanks north star borough",
    ("AK", "prince of wales"): "prince of wales-hyder census area",
}

# Known extinct/discontinued jurisdictions with no clean 1:1 modern successor,
# or non-county placeholder rows (territories/foreign coverage). Reported as
# unmatched with an explanation rather than guessed at.
KNOWN_UNMATCHABLE = {
    ("AK", "valdez-cordova"): "Borough dissolved 2019, split into Chugach + Copper River Census Areas -- no single successor",
    ("AK", "wrangell-petersburg division"): "Dissolved 2008 into separate Wrangell and Petersburg boroughs -- no single successor",
    ("VA", "south boston city"): "Independent city merged into Halifax County in 1995 -- no longer exists",
}
NON_COUNTY_PREFIXES = {"CI", "CZ", "GU", "PI"}  # Caribbean Islands / Canal Zone / Guam / Pacific Islands placeholder rows


def strip_state_suffix(name, state):
    # IBEW county_name is typically "County Name Suffix, ST" -- strip the trailing ", ST"
    m = re.match(r"^(.*),\s*([A-Za-z]{2})$", name.strip())
    if m:
        return m.group(1).strip()
    return name.strip()


distinct_counties = {}
for r in j_rows:
    if not is_us_row(r):
        continue
    key = (r["state_province"], r["county_name"])
    if key not in distinct_counties:
        distinct_counties[key] = r["population"]

print(f"Distinct US counties in jurisdictions.csv: {len(distinct_counties)}")

matched = {}
unmatched = []
unmatchable_notes = {}
for (state, name), pop2000 in distinct_counties.items():
    bare_name = strip_state_suffix(name, state)
    pre = prenormalize(bare_name)

    alias = ALIASES.get((state, pre))
    if alias:
        norm, is_city = normalize_name(alias)
    else:
        norm, is_city = normalize_name(bare_name)

    rec = exact_index.get((state, norm, is_city))
    if rec is None:
        candidates = loose_index.get((state, norm))
        if candidates and len(candidates) == 1:
            rec = candidates[0]
    if rec is None:
        unmatched.append((state, name, pop2000))
        if state in NON_COUNTY_PREFIXES:
            unmatchable_notes[(state, name)] = "Not a US county -- territorial/foreign coverage placeholder row"
        elif (state, pre) in KNOWN_UNMATCHABLE:
            unmatchable_notes[(state, name)] = KNOWN_UNMATCHABLE[(state, pre)]
    else:
        matched[(state, name)] = rec

print(f"Matched: {len(matched)}")
print(f"Unmatched: {len(unmatched)}")
print()
print("Unmatched counties (state, name, population_2000 from IBEW data):")
for state, name, pop2000 in sorted(unmatched, key=lambda x: (x[0], x[1])):
    note = unmatchable_notes.get((state, name), "")
    print(f"  {state:4}{name:40}pop2000={str(pop2000):10}{note}")

# ---- Write joined jurisdictions with population_current ----
fieldnames = list(j_rows[0].keys())
fieldnames_out = []
for fn in fieldnames:
    if fn == "population":
        fieldnames_out.append("population_2000")
    else:
        fieldnames_out.append(fn)
fieldnames_out += ["population_current", "pct_change", "census_fips", "census_match_name"]

out_rows = []
for r in j_rows:
    row = {}
    for fn in fieldnames:
        outfn = "population_2000" if fn == "population" else fn
        row[outfn] = r[fn]
    if is_us_row(r):
        key = (r["state_province"], r["county_name"])
        rec = matched.get(key)
        if rec:
            row["population_current"] = rec["pop2024"]
            row["census_fips"] = rec["fips"]
            row["census_match_name"] = rec["raw_name"]
            try:
                pop2000 = float(r["population"])
                row["pct_change"] = f"{100.0 * (rec['pop2024'] - pop2000) / pop2000:.1f}" if pop2000 else ""
            except (ValueError, ZeroDivisionError):
                row["pct_change"] = ""
        else:
            row["population_current"] = ""
            row["census_fips"] = ""
            row["census_match_name"] = ""
            row["pct_change"] = ""
    else:
        row["population_current"] = ""
        row["census_fips"] = ""
        row["census_match_name"] = ""
        row["pct_change"] = ""
    out_rows.append(row)

with open("out/jurisdictions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames_out)
    w.writeheader()
    w.writerows(out_rows)

print()
print(f"Wrote out/jurisdictions.csv with population_current joined: {len(out_rows)} rows")
