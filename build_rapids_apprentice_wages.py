"""Normalize RAPIDS registration-time apprentice wages by IBEW local.

The RAPIDS apprentice extract is intentionally kept outside the repository in
the source workflow.  This build consumes the already-filtered, local cache
created by ``rapids_kpi.py`` and never writes individual apprentice records.

``STARTING_WAGE`` is a wage reported when an apprentice is registered.  It is
not a current collective-bargaining schedule, so the output keeps the source
label and record counts alongside the median and observed range.  Denied
records, zero/negative wages, and implausible values above $100/hour are not
used in the display statistic, but are counted in the audit columns.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
FILTERED_ROWS = OUT / "_to_delete" / "_rapids_kpi_filtered_rows.csv"
JOIN = OUT / "rapids_kpi_by_lu.csv"
PROGRAMS = ROOT / "raw" / "rapids" / "programs.csv"
TARGETS = OUT / "targets_with_population.csv"
DEST = OUT / "rapids_apprentice_wages.csv"

# The filtered file is emitted without a header by rapids_kpi.py.  These are
# the first columns from apprentices.csv; only these positions are needed.
PS_ID = 3
STATUS = 11
STARTING_WAGE = 19
DENIED_STATUSES = {"DL", "DR", "IR", "PR", "DU"}
MAX_REASONABLE_WAGE = 100.0
DATA_AS_OF = "2026-08-17"
SOURCE_URL = "https://www.apprenticeship.gov/help/what-rapids"

FIELDS = [
    "lu_number", "local_union_id", "ps_ids", "program_names",
    "apprentice_start_hourly_low", "apprentice_start_hourly_median",
    "apprentice_start_hourly_high", "valid_wage_records",
    "denied_records", "zero_or_negative_records", "implausible_records",
    "program_count", "data_as_of", "source_url",
]


def as_float(value: str) -> float | None:
    try:
        parsed = float((value or "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else ""


def summarize(values: list[float]) -> tuple[float, float, float]:
    if not values:
        raise ValueError("summarize requires at least one wage")
    return min(values), statistics.median(values), max(values)


def load_program_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if not PROGRAMS.exists():
        return names
    with PROGRAMS.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ps_id = (row.get("PS_ID") or "").strip()
            if ps_id and row.get("PROG_NAME"):
                names[ps_id] = " ".join(row["PROG_NAME"].split())
    return names


def build() -> list[dict[str, str]]:
    if not FILTERED_ROWS.exists():
        raise FileNotFoundError(
            f"{FILTERED_ROWS} not found; run rapids_kpi.py first or provide its filtered cache"
        )
    if not JOIN.exists():
        raise FileNotFoundError(f"{JOIN} not found; run rapids_kpi_join_locals.py first")

    local_rows = list(csv.DictReader(JOIN.open(encoding="utf-8", newline="")))
    local_union_ids = {}
    if TARGETS.exists():
        with TARGETS.open(encoding="utf-8", newline="") as f:
            local_union_ids = {r["lu_number"]: r.get("local_union_id", "") for r in csv.DictReader(f)}
    ps_to_locals: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in local_rows:
        ps_id = (row.get("ps_id") or "").strip()
        if ps_id:
            ps_to_locals[ps_id].append(row)

    program_names = load_program_names()
    wages: dict[str, list[float]] = defaultdict(list)
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {
        "denied": 0, "zero": 0, "implausible": 0,
    })
    ps_by_lu: dict[str, set[str]] = defaultdict(set)

    with FILTERED_ROWS.open(encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.reader(f):
            if len(row) <= STARTING_WAGE:
                continue
            ps_id = row[PS_ID].strip()
            matches = ps_to_locals.get(ps_id)
            if not matches:
                continue
            status = row[STATUS].strip().upper()
            value = as_float(row[STARTING_WAGE])
            for local in matches:
                lu = local["lu_number"]
                ps_by_lu[lu].add(ps_id)
                if status in DENIED_STATUSES:
                    stats[lu]["denied"] += 1
                    continue
                if value is None:
                    continue
                if value <= 0:
                    stats[lu]["zero"] += 1
                elif value > MAX_REASONABLE_WAGE:
                    stats[lu]["implausible"] += 1
                else:
                    wages[lu].append(value)

    output: list[dict[str, str]] = []
    for local in local_rows:
        lu = local["lu_number"]
        values = wages.get(lu, [])
        if not values:
            continue
        low, median, high = summarize(values)
        ps_ids = sorted(ps_by_lu.get(lu, set()))
        names = sorted({program_names[p] for p in ps_ids if program_names.get(p)})
        counts = stats[lu]
        output.append({
            "lu_number": lu,
            "local_union_id": local_union_ids.get(lu, ""),
            "ps_ids": ";".join(ps_ids),
            "program_names": " | ".join(names),
            "apprentice_start_hourly_low": fmt(low),
            "apprentice_start_hourly_median": fmt(median),
            "apprentice_start_hourly_high": fmt(high),
            "valid_wage_records": str(len(values)),
            "denied_records": str(counts["denied"]),
            "zero_or_negative_records": str(counts["zero"]),
            "implausible_records": str(counts["implausible"]),
            "program_count": str(len(ps_ids)),
            "data_as_of": DATA_AS_OF,
            "source_url": SOURCE_URL,
        })

    output.sort(key=lambda r: int(r["lu_number"]) if r["lu_number"].isdigit() else r["lu_number"])
    with DEST.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    return output


if __name__ == "__main__":
    rows = build()
    print(f"RAPIDS apprentice wage rows: {len(rows)} locals")
    print(f"valid wage records: {sum(int(r['valid_wage_records']) for r in rows)}")
    print(f"wrote {DEST}")
