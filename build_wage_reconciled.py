"""Reconcile the on-disk wage lead list into one conservative row per local.

This is a build script, not an extractor: it reads the already-created
candidate CSV and bounded snippets from the already-crawled raw files.  It
never connects to the network and never writes raw data.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date

from wage_rules import (
    TODAY,
    classify_wage_candidate,
    date_is_recent,
    extract_effective_date,
)

csv.field_size_limit(10_000_000)

FIELDS = [
    "local_union_id", "lu_number", "charter_city", "population",
    "journeyman_base_low", "journeyman_base_high",
    "journeyman_package_low", "journeyman_package_high",
    "apprentice_start_hourly", "apprentice_start_pct", "apprentice_top_pct",
    "progression_json", "effective_date", "effective_date_precision",
    "candidate_count", "admitted_count", "evidence_quote", "source_file",
    "consistency_check", "tier",
]


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def money(value):
    return f"{value:.2f}" if value is not None else ""


def _source_excerpt(row):
    """Find a bounded raw window for date evidence, without returning a page."""
    path = row.get("source_file", "")
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return ""
    raw = str(row.get("parsed_value", "") or "").strip()
    if not raw:
        return ""
    patterns = [rf"\$\s*{re.escape(raw)}(?:\b|[^\d])", rf"\b{re.escape(raw)}\s*%"]
    hits = []
    for pattern in patterns:
        hits.extend(m.start() for m in re.finditer(pattern, text, re.I))
    if not hits:
        return ""
    # Prefer an occurrence whose nearby text resembles the candidate and has
    # explicit date language.  The returned text remains only a small window.
    needle_words = set(re.findall(r"[a-z]{4,}", row.get("matched_text", "").lower()))
    best = None
    for pos in hits:
        window = text[max(0, pos - 500):min(len(text), pos + 700)]
        words = set(re.findall(r"[a-z]{4,}", window.lower()))
        score = len(needle_words & words) + (30 if re.search(r"\b(?:effective|as\s+of|current|rates?)\b", window, re.I) else 0)
        if best is None or score > best[0]:
            best = (score, window)
    return best[1].replace("\r", " ").replace("\n", " ")[:1400] if best else ""


def _date_for(row):
    context = row.get("matched_text", "")
    found = extract_effective_date(context)
    if found[1] != "none":
        return found
    excerpt = _source_excerpt(row)
    found = extract_effective_date(excerpt)
    if found[1] != "none":
        return found
    # A dated wage-sheet filename is a weak but explicit year-level caption;
    # retain year precision rather than inventing a month or day.
    name = os.path.basename(row.get("source_file", ""))
    years = [int(y) for y in re.findall(r"20\d{2}", name)]
    if years and re.search(r"(?:wage|rate|scale|pay|apprentice|inside)", name, re.I):
        year = max(years)
        return f"{year:04d}-01-01", "year"
    return "", "none"


def _source_url(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
        return first if first.startswith(("http://", "https://")) else ""
    except OSError:
        return ""


def _same_table_noise(row, kind):
    text = row.get("matched_text", "")
    # In the real LU 82 table, the second and third numeric columns are fringe
    # benefits and total package.  They are not apprentice hourly pay.  The
    # first column is retained when the row explicitly names an apprentice.
    if kind == "apprentice_hourly" and re.search(r"hourly\s+rate.*fringe|fringe\s+benefits.*total\s+package", text, re.I):
        value = row.get("parsed_value", "")
        if re.search(rf"\$\s*{re.escape(value)}\s*\|\s*\$", text):
            return False
    return True


def _consistency(apprentice_hourly, apprentice_pct, base_low):
    if apprentice_hourly is None or apprentice_pct is None or base_low is None:
        return "insufficient_data"
    expected = apprentice_pct / 100.0 * base_low
    return "pass" if abs(apprentice_hourly - expected) <= expected * 0.15 else "fail"


def reconcile():
    candidates = load("out/wage_candidates.csv")
    targets = load("out/targets_with_population.csv")
    by_lu = defaultdict(list)
    reasons = Counter()
    for row in candidates:
        lu = row.get("lu_number", "")
        context = row.get("matched_text", "")
        if row.get("match_type") == "progression_table":
            result = {"admissible": False, "reject_reason": "progression_table", "kind": "unknown", "value": None}
        else:
            result = classify_wage_candidate(row, context)
        reasons[result.get("reject_reason", "admitted") if not result.get("admissible") else "admitted"] += 1
        row = dict(row)
        row["result"] = result
        row["effective_date"], row["effective_date_precision"] = _date_for(row)
        by_lu[lu].append(row)

    reconciled = []
    failures = []
    for target in targets:
        lu = target["lu_number"]
        rows = by_lu.get(lu, [])
        admitted = [r for r in rows if r["result"].get("admissible") and _same_table_noise(r, r["result"].get("kind"))]
        values = defaultdict(list)
        for r in admitted:
            values[r["result"]["kind"]].append((float(r["result"]["value"]), r))

        base = values["journeyman_base"]
        package = values["journeyman_total_package"]
        hourly = values["apprentice_hourly"]
        pcts = values["apprentice_pct"]
        year_values = []
        for value, r in hourly:
            text = r.get("matched_text", "")
            ym = re.search(r"\b(?:1st|first)\s+year\b|\byear\s*1\b", text, re.I)
            year = 1 if ym else None
            if year is None:
                m = re.search(r"\b(\d)(?:st|nd|rd|th)?\s+year\b|\byear\s*(\d)\b", text, re.I)
                year = int(m.group(1) or m.group(2)) if m else None
            year_values.append({"year": year, "hourly": value})
        starts = [v for v in year_values if v["year"] == 1]
        start_hourly = min((v["hourly"] for v in starts), default=min((v for v, _ in hourly), default=None))
        start_pcts = [v for v, r in pcts if re.search(r"\b(?:start|begin|first)\b", r.get("matched_text", ""), re.I)]
        start_pct = min(start_pcts, default=min((v for v, _ in pcts), default=None))
        top_pcts = [v for v, r in pcts if re.search(r"\b(?:top|last|maximum|progress|up to)\b", r.get("matched_text", ""), re.I)]
        top_pct = max(top_pcts, default=max((v for v, _ in pcts), default=None))

        base_low = min((v for v, _ in base), default=None)
        base_high = max((v for v, _ in base), default=None)
        package_low = min((v for v, _ in package), default=None)
        package_high = max((v for v, _ in package), default=None)
        consistency = _consistency(start_hourly, start_pct, base_low)
        if consistency == "fail":
            failures.append((lu, start_hourly, start_pct, base_low))

        dated = [(r["effective_date"], r["effective_date_precision"], r) for r in admitted if r.get("effective_date")]
        dated.sort(key=lambda x: x[0], reverse=True)
        effective_date, precision = (dated[0][0], dated[0][1]) if dated else ("", "none")
        quote_row = max(admitted, key=lambda r: (bool(r.get("effective_date")), len(r.get("matched_text", ""))), default=None)
        quote = (quote_row or {}).get("matched_text", "")[:300]
        source = (quote_row or {}).get("source_file", "")
        has_independent = len({r.get("source_file", "") for r in admitted}) >= 2
        privileged = any(r.get("match_type") in ("explicit_rate_base_wage", "pct_of_journeyman") for r in admitted)
        recent = date_is_recent(effective_date, precision)
        has_apprentice_signal = start_hourly is not None or start_pct is not None
        display = bool(admitted and has_apprentice_signal and consistency != "fail" and recent and (has_independent or privileged))
        tier = "display" if display else ("review" if admitted else "reject")
        progression = [x for x in sorted(year_values, key=lambda x: (x["year"] is None, x["year"] or 99, x["hourly"]))]
        reconciled.append({
            "local_union_id": target["local_union_id"], "lu_number": lu,
            "charter_city": target.get("charter_city", ""),
            "population": target.get("population_current_served_inside", ""),
            "journeyman_base_low": money(base_low), "journeyman_base_high": money(base_high),
            "journeyman_package_low": money(package_low), "journeyman_package_high": money(package_high),
            "apprentice_start_hourly": money(start_hourly), "apprentice_start_pct": money(start_pct),
            "apprentice_top_pct": money(top_pct), "progression_json": json.dumps(progression, separators=(",", ":")),
            "effective_date": effective_date, "effective_date_precision": precision,
            "candidate_count": len(rows), "admitted_count": len(admitted),
            "evidence_quote": quote, "source_file": source,
            "consistency_check": consistency, "tier": tier,
        })

    with open("out/wage_reconciled.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(reconciled)
    with open("out/wage_blockers.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["lu_number", "blocker", "details"])
        writer.writeheader()
        for lu, hourly_value, pct, base_value in failures:
            writer.writerow({"lu_number": lu, "blocker": "consistency_check_fail", "details": f"hourly={hourly_value}; pct={pct}; base={base_value}"})

    tier_counts = Counter(r["tier"] for r in reconciled)
    print(f"wage candidates: {len(candidates)}")
    print("rejections:", ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    print("tiers:", dict(sorted(tier_counts.items())))
    print("consistency:", dict(Counter(r["consistency_check"] for r in reconciled)))
    print("consistency failures:", failures)
    return reconciled, reasons


if __name__ == "__main__":
    reconcile()
