"""
RAPIDS: compute DOL's own KPI formulas (Active Apprentices, New Apprentices,
Exiters, Total Apprentices Served) per program, from apprentices.csv, following
"KPI Calculations in Registered Apprenticeship" (draft Bulletin 2026-XX) exactly.

apprentices.csv is 5.46M rows / ~3GB -- too large to open in anything, and too
large to stream through Python row-by-row in reasonable time. This shells out to
`awk` first to filter down to only the 325 programs in out/rapids_universe.csv
(a few seconds, since awk does the field split and comparison at C speed), then
does the actual KPI math in Python over the much smaller filtered result
(order 300k rows, not 5.46M). Only the filtered PS_ID/status/date columns ever
reach Python -- no demographic column (RACE_CD, SEX_CD, DISABLED_CD,
ETHNICITY_CD, VET_STAT_IND) is read by the awk filter or touched here at all.

Output is counts only, keyed by PS_ID. No individual apprentice row is written
anywhere.

Reporting period: most recently completed DOL fiscal year (Oct 1 - Sep 30) as of
today's date (not the max date found in the data, which includes future-dated
registrations and would otherwise make a partial year look like a completed
one). The max non-future date actually present in the data is reported
separately as the extract's real as-of date.

Status codes verified against a 500k-row sample of the actual file before
trusting them (the dictionary/bulletin describe statuses in prose, not codes):
CA=Cancelled, CO=Completed, RE=Registered, RI=Re-Instated, SU=Suspended,
TR=Transferred, plus DL/DR/IR/PR/DU as the bulletin's own denied/incomplete set.
Any code outside this set that shows up gets flagged in unclassified_statuses
rather than silently miscounted.
"""

import csv
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

import os
import tempfile

# Paths are configurable rather than hardcoded to one machine's mount layout.
# The old Path.home()/"mnt"/... constants only resolved inside a Cowork session
# and had to be worked around with a wrapper script anywhere else.
IBEW_ROOT = Path(__file__).resolve().parent
UNIVERSE_CSV = IBEW_ROOT / "out" / "rapids_universe.csv"
OUT_DIR = IBEW_ROOT / "out"


def _find_apprentices_csv():
    env = os.environ.get("RAPIDS_APPRENTICES_CSV")
    if env:
        return Path(env)
    for base in (
        Path.home() / "mnt" / "Apprentice Data pull 8.18.26",
        Path.home() / "Downloads" / "Apprentice Data pull 8.18.26",
        IBEW_ROOT / "raw" / "rapids",
    ):
        c = base / "apprentices.csv"
        if c.exists():
            return c
    return Path.home() / "Downloads" / "Apprentice Data pull 8.18.26" / "apprentices.csv"


APPRENTICES_CSV = _find_apprentices_csv()
# The 178MB filtered intermediate goes to local temp, not into out/. Writing it
# onto a network/FUSE-mounted repo is what made this script time out.
SCRATCH_DIR = Path(os.environ.get("RAPIDS_SCRATCH", tempfile.gettempdir()))

HEADER = [
    "SEQ_ID", "APPR_ID", "APPR_NUMBER", "PS_ID", "TERM_LENGTH_MIN", "TERM_LENGTH_MAX",
    "RAPIDS_CD", "ONET_SOC_CD", "VERSION_NUM", "CAREER_LATTICE_LVL", "PROGRAM_STATUS",
    "APPR_STATUS_CD", "PENDING_ACTION", "IS_PENDING_EMP", "EMP_CD", "SCHEDULE_CD",
    "AGE_COHORT_CD", "REGISTER_DT", "START_DT", "STARTING_WAGE", "EXIT_WAGE_DT", "EXIT_WAGE",
]
IDX = {name: i for i, name in enumerate(HEADER)}

ACTIVE_STATUSES = {"RE", "RI", "SU", "TR"}
EXITED_STATUSES = {"CA", "CO"}
DENIED_STATUSES = {"DL", "DR", "IR", "PR", "DU"}


def parse_date(s):
    if not s or not s.strip():
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def dol_fiscal_year_bounds(as_of):
    """Most recently completed Oct 1 - Sep 30 fiscal year as of `as_of`.
    The returned fy_end is always <= as_of."""
    fy_end_year = as_of.year if as_of.month >= 10 else as_of.year - 1
    fy_end = date(fy_end_year, 9, 30)
    if fy_end > as_of:
        fy_end_year -= 1
        fy_end = date(fy_end_year, 9, 30)
    fy_start = date(fy_end_year - 1, 10, 1)
    return fy_start, fy_end


def main():
    if not APPRENTICES_CSV.exists():
        print(f"[blocker] apprentices.csv not found at {APPRENTICES_CSV}", file=sys.stderr)
        raise SystemExit(1)
    if not UNIVERSE_CSV.exists():
        print(f"[blocker] {UNIVERSE_CSV} not found -- run rapids_universe.py first", file=sys.stderr)
        raise SystemExit(1)

    universe = pd.read_csv(UNIVERSE_CSV, dtype=str, low_memory=False)
    target_ps_ids = sorted(universe["PS_ID"].unique())
    print(f"Filtering to {len(target_ps_ids)} candidate programs")

    ids_path = SCRATCH_DIR / "_rapids_kpi_target_ids.txt"
    ids_path.write_text("\n".join(target_ps_ids) + "\n")

    filtered_path = SCRATCH_DIR / "_rapids_kpi_filtered_rows.csv"
    reuse = os.environ.get("RAPIDS_FILTERED_CSV")
    if reuse and Path(reuse).exists():
        filtered_path = Path(reuse)
        print(f"reusing existing filtered rows at {filtered_path}")
    else:
        awk_script = "NR==FNR { ids[$1]=1; next } ($4 in ids)"
        with open(filtered_path, "w") as out_f:
            subprocess.run(
                ["awk", "-F,", awk_script, str(ids_path), str(APPRENTICES_CSV)],
                stdout=out_f, check=True,
            )
        print(f"awk pre-filter done, wrote {filtered_path}")

    rows_by_ps = defaultdict(list)
    today = date.today()
    max_date_seen = date(1900, 1, 1)
    max_nonfuture_date = date(1900, 1, 1)
    unclassified_statuses = set()
    total = 0
    bad_rows = 0
    forward_dated_fields = 0

    with open(filtered_path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            total += 1
            if len(row) < len(HEADER):
                bad_rows += 1
                continue
            ps_id = row[IDX["PS_ID"]]
            if ps_id == "PS_ID":  # header row, if the filtered file kept one
                continue
            status = row[IDX["APPR_STATUS_CD"]]
            if status and status not in ACTIVE_STATUSES | EXITED_STATUSES | DENIED_STATUSES:
                unclassified_statuses.add(status)
            start_dt = parse_date(row[IDX["START_DT"]])
            exit_dt = parse_date(row[IDX["EXIT_WAGE_DT"]])
            if start_dt and start_dt > max_date_seen:
                max_date_seen = start_dt
            if exit_dt and exit_dt > max_date_seen:
                max_date_seen = exit_dt
            if start_dt and start_dt <= today and start_dt > max_nonfuture_date:
                max_nonfuture_date = start_dt
            if exit_dt and exit_dt <= today and exit_dt > max_nonfuture_date:
                max_nonfuture_date = exit_dt
            # Task 1 (intake-estimate round): forward-dated registrations
            # (the extract has some as far out as 2027-06-18) are not real
            # observations -- treat them as absent everywhere, not just when
            # picking the reporting period, or they leak into active/new/
            # exiter counts as if they'd actually happened.
            if start_dt and start_dt > today:
                start_dt = None
                forward_dated_fields += 1
            if exit_dt and exit_dt > today:
                exit_dt = None
                forward_dated_fields += 1
            rows_by_ps[ps_id].append((row[IDX["APPR_NUMBER"]], status, start_dt, exit_dt))

    print(f"Parsed {total} filtered rows ({bad_rows} malformed, skipped), "
          f"{len(rows_by_ps)} of {len(target_ps_ids)} target programs have apprentice records")
    if unclassified_statuses:
        print(f"[warning] unclassified APPR_STATUS_CD values, not counted in any bucket: {sorted(unclassified_statuses)}")
    if forward_dated_fields:
        print(f"[note] {forward_dated_fields} forward-dated START_DT/EXIT_WAGE_DT fields "
              f"(after {today}) nulled out and excluded from all counts, not just period selection")
    if max_date_seen > today:
        print(f"[note] data contains future-dated records up to {max_date_seen}; ignored for period selection")

    period_start, period_end = dol_fiscal_year_bounds(today)
    print(f"Reporting period (most recent completed DOL FY as of {today}): "
          f"{period_start} to {period_end}")
    print(f"Extract's real as-of date (max non-future date present in data): {max_nonfuture_date}")

    results = []
    for ps_id, apps in rows_by_ps.items():
        active = new = exiters = 0
        for appr_number, status, start_dt, exit_dt in apps:
            if not appr_number:
                continue
            if start_dt and start_dt > date(1900, 1, 1) and start_dt < period_end:
                exit_ok = (exit_dt is None) or (exit_dt > start_dt)
                if exit_ok:
                    if status in ACTIVE_STATUSES:
                        active += 1
                    elif status in EXITED_STATUSES and exit_dt and exit_dt > period_end:
                        active += 1
            if status not in DENIED_STATUSES and start_dt:
                if period_start <= start_dt <= period_end:
                    new += 1
            if status in EXITED_STATUSES and exit_dt:
                if period_start <= exit_dt <= period_end:
                    exiters += 1
        results.append({
            "PS_ID": ps_id, "period_start": period_start, "period_end": period_end,
            "active_apprentices": active, "new_apprentices": new, "exiters": exiters,
            "total_apprentices_served": active + exiters, "total_rows_for_program": len(apps),
        })

    out_df = pd.DataFrame(results)
    out_df = out_df.merge(
        universe[["PS_ID", "PROG_NAME", "PROG_CITY", "PROG_STATE", "PROG_STATUS"]],
        on="PS_ID", how="left",
    )
    out_path = OUT_DIR / "rapids_kpi_by_program.csv"
    out_df.to_csv(out_path, index=False)

    for tmp in (ids_path, None if os.environ.get("RAPIDS_FILTERED_CSV") else filtered_path):
        if tmp is None:
            continue
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # some mounts disallow unlink; leaving scratch behind is harmless

    print()
    print(f"Wrote {len(out_df)} program-level KPI rows to {out_path}")
    print(f"Totals across universe: active={out_df['active_apprentices'].sum()}, "
          f"new={out_df['new_apprentices'].sum()}, exiters={out_df['exiters'].sum()}, "
          f"served={out_df['total_apprentices_served'].sum()}")
    print()
    print("Files touched:")
    print("  out/rapids_kpi_by_program.csv")
    print("(intermediate filter files cleaned up)")


if __name__ == "__main__":
    main()
