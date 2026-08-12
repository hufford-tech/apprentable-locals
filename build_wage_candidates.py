"""out/wage_candidates.csv -- free deterministic wage mining over pages already
crawled to disk in raw/crawl/local/<lu>/*.md and raw/crawl/jatc/<domain>/*.md
(frontend task 3). Regex over text already on disk, zero network, zero API cost.

Explicitly NOT written into frontend_data.json / displayed anywhere -- candidates
only, for a human to review. Regex over raw HTML/markdown is exactly what produced
the "Applicants Apply Online" defect on this project; treat every hit as a lead,
not a fact.
"""
import csv
import os
import re
from collections import defaultdict

csv.field_size_limit(10_000_000)


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


targets = load("out/targets_with_population.csv")
lu_to_lid = {t["lu_number"]: t["local_union_id"] for t in targets}
target_lus = set(lu_to_lid)

local_to_jatc = defaultdict(list)
for r in load("out/local_to_jatc.csv"):
    local_to_jatc[r["lu_number"]].append(r["jatc_domain"])

WAGE_VOCAB = r"(wage|rate|scale|per\s*hour|hourly|journeyman|journeyperson|apprentice)"
DOLLAR_RE = re.compile(r"\$\s?\d{1,3}(\.\d{1,2})?")
PCT_JOURNEY_RE = re.compile(
    r"\b(\d{2,3})\s?%\s*(of\s+)?(the\s+)?journey(man|person)?\b"
    r"|\bstarts?\s+at\s+(\d{2,3})\s?%",
    re.IGNORECASE,
)
PACKAGE_RE = re.compile(r"\btotal\s+package\b|\bpackage\s+rate\b|\bfringe\b|\bbenefits?\s+package\b", re.IGNORECASE)
BASE_RE = re.compile(r"\bbase\s+(wage|rate|pay)\b", re.IGNORECASE)
PERIOD_RE = re.compile(
    r"\b(1st|2nd|3rd|4th|5th|6th|7th|8th|first|second|third|fourth|fifth|sixth|"
    r"year\s*1|year\s*2|year\s*3|year\s*4|year\s*5|\d(st|nd|rd|th)?\s*(year|period|term|step))\b",
    re.IGNORECASE,
)


def context(text, start, end, span=80):
    lo = max(0, start - span)
    hi = min(len(text), end + span)
    return text[lo:hi].replace("\n", " ").replace("\r", " ").strip()


def scan_file(text):
    """Yield (match_type, matched_text, parsed_value, confidence) for one page."""
    hits = []

    for m in DOLLAR_RE.finditer(text):
        window = text[max(0, m.start() - 80):min(len(text), m.end() + 80)]
        if re.search(WAGE_VOCAB, window, re.IGNORECASE):
            is_package = bool(PACKAGE_RE.search(window))
            is_base = bool(BASE_RE.search(window))
            mtype = (
                "explicit_rate_total_package" if is_package else
                "explicit_rate_base_wage" if is_base else
                "explicit_rate"
            )
            hits.append((
                mtype,
                context(text, m.start(), m.end()),
                m.group(0).replace(" ", "").replace("$", ""),
                "medium" if (is_package or is_base) else "low",
            ))

    for m in PCT_JOURNEY_RE.finditer(text):
        val = m.group(1) or m.group(5)
        hits.append((
            "pct_of_journeyman",
            context(text, m.start(), m.end()),
            val,
            "medium",
        ))

    # progression table: 3+ period markers within a short span of text = a table
    period_positions = [m.start() for m in PERIOD_RE.finditer(text)]
    if len(period_positions) >= 3:
        clustered = 0
        for i in range(1, len(period_positions)):
            if period_positions[i] - period_positions[i - 1] < 200:
                clustered += 1
        if clustered >= 2:
            first, last = period_positions[0], period_positions[-1]
            hits.append((
                "progression_table",
                context(text, first, min(last, first + 300), span=40),
                "",
                "low",
            ))

    return hits


rows = []
per_local_types = defaultdict(set)

for lu in sorted(target_lus, key=lambda x: int(x)):
    lid = lu_to_lid[lu]
    files = []
    local_dir = os.path.join("raw", "crawl", "local", lu)
    if os.path.isdir(local_dir):
        files += [os.path.join(local_dir, f) for f in os.listdir(local_dir) if f.endswith(".md")]
    for domain in local_to_jatc.get(lu, ()):
        jatc_dir = os.path.join("raw", "crawl", "jatc", domain)
        if os.path.isdir(jatc_dir):
            files += [os.path.join(jatc_dir, f) for f in os.listdir(jatc_dir) if f.endswith(".md")]

    for path in files:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        for mtype, matched_text, parsed_value, confidence in scan_file(text):
            rows.append({
                "local_union_id": lid,
                "lu_number": lu,
                "source_file": path.replace("\\", "/"),
                "match_type": mtype,
                "matched_text": matched_text[:200],
                "parsed_value": parsed_value,
                "confidence": confidence,
            })
            per_local_types[lu].add(mtype)

with open("out/wage_candidates.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["local_union_id", "lu_number", "source_file", "match_type",
                  "matched_text", "parsed_value", "confidence"]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)

# hit rate report
locals_with_hit = set(per_local_types)
by_type_locals = defaultdict(set)
for lu, types in per_local_types.items():
    for t in types:
        by_type_locals[t].add(lu)

print(f"targets: {len(target_lus)}")
print(f"locals with >=1 candidate: {len(locals_with_hit)} "
      f"({100*len(locals_with_hit)/len(target_lus):.1f}%)")
print(f"total candidate rows: {len(rows)}")
print("hit rate by match_type (locals with >=1 hit of that type):")
for t, lus in sorted(by_type_locals.items(), key=lambda x: -len(x[1])):
    print(f"   {t}: {len(lus)} locals ({100*len(lus)/len(target_lus):.1f}%)")
