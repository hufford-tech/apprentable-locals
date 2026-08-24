# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/build_scoped_closure_audit.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

"""out/scoped_closure_audit.csv -- audit every statement_type == 'closed' in
extraction_v2.csv for a scope limiter (a specific month/date, a named program
other than inside wireman, a class/cohort year, or words like except/only/
during/until) that would mean the closure isn't a blanket "not accepting"
(frontend task 2).

Audit only -- does not touch compute_status. Zero network.
"""
import csv
import json
import re
from collections import defaultdict

csv.field_size_limit(10_000_000)


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


targets = {t["lu_number"]: t for t in load("out/targets_with_population.csv")}
computed = {c["lu_number"]: c for c in load("out/computed_status.csv")}
extraction = load("out/extraction_v2.csv")

MONTHS = (
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan\.|feb\.|mar\.|apr\.|jun\.|jul\.|aug\.|sep\.|sept\.|"
    r"oct\.|nov\.|dec\."
)
DATE_RE = re.compile(
    rf"\b({MONTHS})\b(\s+\d{{1,2}}(st|nd|rd|th)?)?(,?\s*\d{{4}})?"
    rf"|\b\d{{1,2}}/\d{{1,2}}(/\d{{2,4}})?\b",
    re.IGNORECASE,
)
CLASS_YEAR_RE = re.compile(r"\bclass\s+of\s+\d{4}\b|\b\d{4}\s+(program|class|cohort)\b", re.IGNORECASE)
LIMITER_WORDS_RE = re.compile(
    r"\bexcept\b|\bother than\b|\bonly\b|\bduring\b|\bfor the month of\b|\buntil\b",
    re.IGNORECASE,
)
NAMED_PROGRAM_RE = re.compile(
    r"\b(outside|lineman|line\s*worker|residential|commercial|sound\s*(and|&)\s*communications|"
    r"telecom(munications)?|utility|clerical|tree\s*trim(ming)?|voice[- ]data[- ]video|vdv)\b",
    re.IGNORECASE,
)


def find_limiters(text):
    hits = []
    if DATE_RE.search(text):
        hits.append("date/month")
    if CLASS_YEAR_RE.search(text):
        hits.append("class/cohort year")
    m = NAMED_PROGRAM_RE.search(text)
    if m:
        hits.append(f"named program ({m.group(0).lower()})")
    m2 = LIMITER_WORDS_RE.search(text)
    if m2:
        hits.append(f"limiter word ({m2.group(0).lower()})")
    return hits


rows = []
for e in extraction:
    lu = e["lu_number"]
    if not e.get("status_statements_json"):
        continue
    try:
        stmts = json.loads(e["status_statements_json"])
    except json.JSONDecodeError:
        continue
    for s in stmts:
        if (s.get("statement_type") or "").strip().lower() != "closed":
            continue
        text = s.get("verbatim_text") or ""
        limiters = find_limiters(text)
        t = targets.get(lu, {})
        c = computed.get(lu, {})
        rows.append({
            "local_union_id": t.get("local_union_id", ""),
            "lu_number": lu,
            "charter_city": t.get("charter_city", ""),
            "population": t.get("population_current_served_inside", ""),
            "verbatim_text": text[:300],
            "source_url": s.get("source_url", ""),
            "scope_limiter_found": "; ".join(limiters),
            "current_status": c.get("computed_status", ""),
            "likely_misread": bool(limiters),
        })

with open("out/scoped_closure_audit.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["local_union_id", "lu_number", "charter_city", "population",
                  "verbatim_text", "source_url", "scope_limiter_found",
                  "current_status", "likely_misread"]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)

flagged = [r for r in rows if r["likely_misread"]]


def pop_int(r):
    try:
        return int(float(r["population"] or 0))
    except ValueError:
        return 0


flagged.sort(key=pop_int, reverse=True)

print(f"'closed' statements audited: {len(rows)}")
print(f"scope-limited (likely misread): {len(flagged)}")
print("five largest by population:")
for r in flagged[:5]:
    print(f"   LU {r['lu_number']}  {r['charter_city']}  pop={pop_int(r):,}  "
          f"[{r['scope_limiter_found']}]  \"{r['verbatim_text'][:90]}\"")
