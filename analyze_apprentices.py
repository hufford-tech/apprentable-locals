"""Memory-safe profile and editorial analysis of the RAPIDS apprentice extract.

The 2.8 GB source CSV is never modified and individual apprentice records are
never written. The script scans selected columns in chunks and emits only
aggregate CSV/JSON/PNG artifacts under out/apprentices_analysis.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = (
    Path.home() / "Downloads" / "Apprentice Data pull 8.18.26" / "apprentices.csv"
)
PROGRAMS = ROOT / "raw" / "rapids" / "programs.csv"
OUT = ROOT / "out" / "apprentices_analysis"

AS_OF = pd.Timestamp("2026-08-17")
FY_START = pd.Timestamp("2024-10-01")
FY_END = pd.Timestamp("2025-09-30")
DENIED = {"DL", "DR", "IR", "PR", "DU"}
ACTIVE = {"RE", "RI", "SU", "TR", "UP"}
EXITED = {"CA", "CO"}
ANALYSIS_YEARS = list(range(2015, 2026))

USECOLS = [
    "APPR_ID", "APPR_NUMBER", "PS_ID", "PROGRAM_STATUS", "APPR_STATUS_CD",
    "AGE_COHORT_CD", "START_DT", "STARTING_WAGE", "EXIT_WAGE_DT", "EXIT_WAGE",
    "AGE_AT_START", "ETHNICITY_CD", "VET_STAT_IND", "SEX_CD", "RACE_CD",
    "DISABLED_CD", "EDUCATION_CD", "OCCUP_TYPE", "ACTIVE_FLG",
    "STARTINGWAGEIND", "NAICS_CD", "TERM_LENGTH", "OCCUPATION_TITLE",
    "ONET_SOC_CD",
]

CODE_LABELS = {
    "status": {
        "RE": "Registered",
        "RI": "Reinstated",
        "SU": "Suspended",
        "TR": "Transferred",
        "UP": "Updated",
        "CO": "Completed",
        "CA": "Cancelled",
        "DL": "Denied/incomplete registration",
        "DR": "Denied/incomplete registration",
        "IR": "Denied/incomplete registration",
        "PR": "Denied/incomplete registration",
        "DU": "Denied/incomplete registration",
    },
}


def clean_code(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )


def clean_title(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def update_counter(counter: Counter, series: pd.Series) -> None:
    counter.update({str(k): int(v) for k, v in series.dropna().value_counts().items()})


def update_pair_counter(
    counter: Counter, left: pd.Series, right: pd.Series
) -> None:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if frame.empty:
        return
    grouped = frame.value_counts()
    counter.update({(str(k[0]), str(k[1])): int(v) for k, v in grouped.items()})


def weighted_quantile(counter: Counter, q: float) -> float | None:
    if not counter:
        return None
    total = sum(counter.values())
    target = q * (total - 1)
    cumulative = 0
    for value, count in sorted(counter.items(), key=lambda item: float(item[0])):
        if cumulative + count > target:
            return float(value)
        cumulative += count
    return float(max(counter, key=float))


def pct(num: int | float, den: int | float) -> float | None:
    return None if not den else float(num) / float(den)


def load_program_maps():
    programs = pd.read_csv(PROGRAMS, dtype="string", low_memory=False)
    programs.columns = [str(c).replace("\ufeff", "") for c in programs.columns]
    programs["PS_ID"] = programs["PS_ID"].str.strip()
    duplicate_ps = int(programs["PS_ID"].duplicated(keep=False).sum())
    programs = programs.drop_duplicates("PS_ID", keep="first")
    maps = []
    for col in ("PROG_STATE", "UNION_Y_N", "PROG_NAME", "PROG_STATUS"):
        maps.append(
            programs.set_index("PS_ID")[col].fillna("").astype(str).to_dict()
        )
    meta = {
        "program_rows": int(len(programs)),
        "duplicate_ps_id_rows": duplicate_ps,
    }
    return (*maps, meta)


def font(size: int, bold: bool = False):
    candidates = [
        Path(
            "C:/Windows/Fonts/arialbd.ttf"
            if bold
            else "C:/Windows/Fonts/arial.ttf"
        ),
        Path(
            "C:/Windows/Fonts/calibrib.ttf"
            if bold
            else "C:/Windows/Fonts/calibri.ttf"
        ),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def save_line_chart(
    rows: list[dict],
    x_key: str,
    y_key: str,
    title: str,
    subtitle: str,
    y_label: str,
    path: Path,
    percent: bool = False,
) -> None:
    width, height = 1400, 820
    im = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(im)
    navy, blue, grid, text = "#12304A", "#2477B3", "#D9E2E8", "#26343D"
    d.text((75, 45), title, fill=navy, font=font(40, True))
    d.text((75, 100), subtitle, fill="#5A6B75", font=font(22))
    left, top, right, bottom = 125, 175, 1335, 700
    values = [float(r[y_key]) for r in rows]
    xs = [str(r[x_key]) for r in rows]
    ymin = 0.0
    ymax = max(values) * 1.12 if values else 1.0
    if ymax == 0:
        ymax = 1.0
    for i in range(6):
        yv = ymin + (ymax - ymin) * i / 5
        py = bottom - (bottom - top) * i / 5
        d.line((left, py, right, py), fill=grid, width=2)
        label = f"{yv:.0%}" if percent else f"{yv:,.0f}"
        d.text((left - 18, py), label, fill=text, font=font(19), anchor="rm")
    points = []
    for i, val in enumerate(values):
        px = left + (right - left) * i / max(1, len(values) - 1)
        py = bottom - (bottom - top) * (val - ymin) / (ymax - ymin)
        points.append((px, py))
        d.text((px, bottom + 18), xs[i], fill=text, font=font(18), anchor="ma")
    if len(points) > 1:
        d.line(points, fill=blue, width=6, joint="curve")
    for px, py in points:
        d.ellipse(
            (px - 7, py - 7, px + 7, py + 7),
            fill=blue,
            outline="white",
            width=2,
        )
    d.text(
        (left, top - 34),
        y_label,
        fill=text,
        font=font(19, True),
        anchor="ls",
    )
    d.text(
        (75, 770),
        "Source: U.S. DOL RAPIDS public-use extract, as of 2026-08-17. "
        "Aggregated by Apprentable analysis.",
        fill="#667780",
        font=font(17),
    )
    im.save(path)


def save_bar_chart(
    rows: list[dict],
    label_key: str,
    value_key: str,
    title: str,
    subtitle: str,
    path: Path,
) -> None:
    width, height = 1500, 980
    im = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(im)
    navy, blue, grid, text = "#12304A", "#2477B3", "#E4EBEF", "#26343D"
    d.text((70, 42), title, fill=navy, font=font(40, True))
    d.text((70, 98), subtitle, fill="#5A6B75", font=font(22))
    left, top, right = 500, 175, 1420
    row_h = 64
    maxv = max(float(r[value_key]) for r in rows) if rows else 1
    for i, row in enumerate(rows):
        y = top + i * row_h
        label = str(row[label_key])
        if len(label) > 42:
            label = label[:39] + "..."
        value = float(row[value_key])
        d.text((left - 22, y + 20), label, fill=text, font=font(20), anchor="rm")
        d.rectangle((left, y, right, y + 40), fill=grid)
        x2 = left + (right - left) * value / maxv
        d.rectangle((left, y, x2, y + 40), fill=blue)
        d.text(
            (min(x2 + 12, right - 5), y + 20),
            f"{value:,.0f}",
            fill=text,
            font=font(19, True),
            anchor="lm" if x2 < right - 110 else "rm",
        )
    d.text(
        (70, 930),
        "Source: U.S. DOL RAPIDS public-use extract, as of 2026-08-17. "
        "Aggregated by Apprentable analysis.",
        fill="#667780",
        font=font(17),
    )
    im.save(path)


def write_rows(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def main(source: Path, chunk_size: int) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    if not PROGRAMS.exists():
        raise FileNotFoundError(PROGRAMS)
    OUT.mkdir(parents=True, exist_ok=True)

    prog_state, prog_union, prog_name, prog_status, program_meta = (
        load_program_maps()
    )

    rows = 0
    chunks = 0
    nulls = Counter()
    status_counts = Counter()
    program_status_counts = Counter()
    occ_type_counts = Counter()
    sex_counts = Counter()
    race_counts = Counter()
    ethnicity_counts = Counter()
    education_counts = Counter()
    veteran_counts = Counter()
    age_cohort_counts = Counter()
    starting_wage_ind_counts = Counter()
    start_year_counts = Counter()
    outcome_by_start_year = Counter()
    sex_by_start_year = Counter()
    race_by_start_year = Counter()
    ethnicity_by_start_year = Counter()
    education_by_start_year = Counter()
    veteran_by_start_year = Counter()
    age_hist = Counter()
    age_by_start_year = Counter()
    wage_hist = Counter()
    wage_by_start_year: dict[int, Counter] = defaultdict(Counter)
    uplift_hist = Counter()
    fy_occupation = Counter()
    fy_soc = Counter()
    fy_soc_title = Counter()
    fy_state = Counter()
    fy_union = Counter()
    fy_program_new = Counter()
    fy_program_active = Counter()
    fy_program_exiters = Counter()
    starts_by_year_soc = Counter()

    malformed_dates = Counter()
    future_start_dates = 0
    future_exit_dates = 0
    exit_before_start = 0
    invalid_age = 0
    age_cohort_mismatch = 0
    age_cohort_comparable = 0
    zero_or_negative_start_wage = 0
    implausible_start_wage = 0
    valid_start_wage = 0
    valid_exit_wage = 0
    completed_wage_pairs = 0
    completed_wage_declines = 0
    unmatched_program_rows = 0
    duplicate_appr_ids = 0
    seen_ids = bytearray(8_000_000)
    min_start = max_start = min_exit = max_exit = None
    official_new = official_active = official_exiters = 0
    official_completed = official_cancelled = 0

    reader = pd.read_csv(
        source,
        usecols=USECOLS,
        chunksize=chunk_size,
        low_memory=False,
        on_bad_lines="warn",
    )
    for chunk in reader:
        chunks += 1
        n = len(chunk)
        rows += n
        nulls.update({col: int(chunk[col].isna().sum()) for col in USECOLS})

        ids = (
            pd.to_numeric(chunk["APPR_ID"], errors="coerce")
            .dropna()
            .astype(np.int64)
            .to_numpy()
        )
        if len(ids):
            ids = ids[ids >= 0]
            unique_ids, counts = np.unique(ids, return_counts=True)
            duplicate_appr_ids += int(np.maximum(counts - 1, 0).sum())
            max_id = int(unique_ids.max()) if len(unique_ids) else -1
            if max_id >= len(seen_ids):
                seen_ids.extend(b"\0" * (max_id + 1 - len(seen_ids)))
            seen_array = np.frombuffer(seen_ids, dtype=np.uint8)
            duplicate_appr_ids += int(np.count_nonzero(seen_array[unique_ids]))
            seen_array[unique_ids] = 1

        status = clean_code(chunk["APPR_STATUS_CD"])
        update_counter(status_counts, status)
        update_counter(program_status_counts, clean_code(chunk["PROGRAM_STATUS"]))
        update_counter(occ_type_counts, clean_title(chunk["OCCUP_TYPE"]))
        update_counter(sex_counts, clean_code(chunk["SEX_CD"]))
        update_counter(race_counts, clean_code(chunk["RACE_CD"]))
        update_counter(ethnicity_counts, clean_code(chunk["ETHNICITY_CD"]))
        update_counter(education_counts, clean_code(chunk["EDUCATION_CD"]))
        update_counter(veteran_counts, clean_code(chunk["VET_STAT_IND"]))
        update_counter(age_cohort_counts, clean_code(chunk["AGE_COHORT_CD"]))
        wage_ind = clean_code(chunk["STARTINGWAGEIND"])
        update_counter(starting_wage_ind_counts, wage_ind)

        start_raw = chunk["START_DT"]
        exit_raw = chunk["EXIT_WAGE_DT"]
        start_dt = pd.to_datetime(start_raw, errors="coerce", format="mixed")
        exit_dt = pd.to_datetime(exit_raw, errors="coerce", format="mixed")
        malformed_dates["start"] += int(
            start_raw.notna().sum() - start_dt.notna().sum()
        )
        malformed_dates["exit"] += int(
            exit_raw.notna().sum() - exit_dt.notna().sum()
        )
        future_start_dates += int((start_dt > AS_OF).sum())
        future_exit_dates += int((exit_dt > AS_OF).sum())
        exit_before_start += int(
            ((exit_dt < start_dt) & start_dt.notna() & exit_dt.notna()).sum()
        )
        if start_dt.notna().any():
            cmin, cmax = start_dt.min(), start_dt.max()
            min_start = cmin if min_start is None or cmin < min_start else min_start
            max_start = cmax if max_start is None or cmax > max_start else max_start
        if exit_dt.notna().any():
            cmin, cmax = exit_dt.min(), exit_dt.max()
            min_exit = cmin if min_exit is None or cmin < min_exit else min_exit
            max_exit = cmax if max_exit is None or cmax > max_exit else max_exit

        appr_number_ok = (
            chunk["APPR_NUMBER"].notna()
            & chunk["APPR_NUMBER"].astype("string").str.strip().ne("")
        )
        legitimate = appr_number_ok & ~status.isin(DENIED)
        start_year = start_dt.dt.year.astype("Int64")
        valid_observed_start = (
            legitimate
            & start_dt.notna()
            & (start_dt > pd.Timestamp("1900-01-01"))
            & (start_dt <= AS_OF)
        )
        update_counter(
            start_year_counts, start_year[valid_observed_start].astype("string")
        )
        update_pair_counter(
            outcome_by_start_year,
            start_year[valid_observed_start].astype("string"),
            status[valid_observed_start],
        )

        fy_new = legitimate & start_dt.between(
            FY_START, FY_END, inclusive="both"
        )
        valid_exit_relation = exit_dt.isna() | (exit_dt > start_dt)
        fy_active = (
            appr_number_ok
            & start_dt.notna()
            & (start_dt > pd.Timestamp("1900-01-01"))
            & (start_dt < FY_END)
            & valid_exit_relation
            & (status.isin(ACTIVE) | (status.isin(EXITED) & (exit_dt > FY_END)))
        )
        fy_exit = (
            appr_number_ok
            & status.isin(EXITED)
            & exit_dt.between(FY_START, FY_END, inclusive="both")
        )
        official_new += int(fy_new.sum())
        official_active += int(fy_active.sum())
        official_exiters += int(fy_exit.sum())
        official_completed += int((fy_exit & status.eq("CO")).sum())
        official_cancelled += int((fy_exit & status.eq("CA")).sum())

        ps_id = (
            pd.to_numeric(chunk["PS_ID"], errors="coerce")
            .astype("Int64")
            .astype("string")
        )
        states = ps_id.map(prog_state).replace("", pd.NA)
        unions = ps_id.map(prog_union).replace("", pd.NA)
        unmatched_program_rows += int(states.isna().sum())
        update_counter(fy_state, states[fy_new])
        update_counter(fy_union, unions[fy_new])
        update_counter(fy_program_new, ps_id[fy_new])
        update_counter(fy_program_active, ps_id[fy_active])
        update_counter(fy_program_exiters, ps_id[fy_exit])

        titles = clean_title(chunk["OCCUPATION_TITLE"])
        socs = clean_code(chunk["ONET_SOC_CD"])
        update_counter(fy_occupation, titles[fy_new])
        update_counter(fy_soc, socs[fy_new])
        update_pair_counter(fy_soc_title, socs[fy_new], titles[fy_new])

        for year in ANALYSIS_YEARS:
            ym = valid_observed_start & start_year.eq(year)
            if not ym.any():
                continue
            update_pair_counter(
                sex_by_start_year,
                start_year[ym].astype("string"),
                clean_code(chunk.loc[ym, "SEX_CD"]),
            )
            update_pair_counter(
                race_by_start_year,
                start_year[ym].astype("string"),
                clean_code(chunk.loc[ym, "RACE_CD"]),
            )
            update_pair_counter(
                ethnicity_by_start_year,
                start_year[ym].astype("string"),
                clean_code(chunk.loc[ym, "ETHNICITY_CD"]),
            )
            update_pair_counter(
                education_by_start_year,
                start_year[ym].astype("string"),
                clean_code(chunk.loc[ym, "EDUCATION_CD"]),
            )
            update_pair_counter(
                veteran_by_start_year,
                start_year[ym].astype("string"),
                clean_code(chunk.loc[ym, "VET_STAT_IND"]),
            )
            update_pair_counter(
                starts_by_year_soc,
                start_year[ym].astype("string"),
                socs[ym],
            )

        age = pd.to_numeric(chunk["AGE_AT_START"], errors="coerce")
        valid_age = valid_observed_start & age.between(14, 80, inclusive="both")
        invalid_age += int(
            (age.notna() & ~age.between(14, 80, inclusive="both")).sum()
        )
        update_counter(
            age_hist,
            age[valid_age].round().astype("Int64").astype("string"),
        )
        update_pair_counter(
            age_by_start_year,
            start_year[valid_age].astype("string"),
            age[valid_age].round().astype("Int64").astype("string"),
        )
        cohort = pd.to_numeric(chunk["AGE_COHORT_CD"], errors="coerce")
        comparable = valid_age & cohort.isin([1, 2, 3])
        expected = pd.Series(
            np.select([age <= 24, age <= 34], [1, 2], default=3),
            index=chunk.index,
        )
        age_cohort_comparable += int(comparable.sum())
        age_cohort_mismatch += int((comparable & cohort.ne(expected)).sum())

        start_wage = pd.to_numeric(chunk["STARTING_WAGE"], errors="coerce")
        exit_wage = pd.to_numeric(chunk["EXIT_WAGE"], errors="coerce")
        zero_or_negative_start_wage += int(
            (start_wage.notna() & (start_wage <= 0)).sum()
        )
        implausible_start_wage += int((start_wage > 100).sum())
        valid_sw = (
            legitimate
            & wage_ind.eq("H")
            & start_wage.gt(0)
            & start_wage.le(100)
        )
        valid_ew = exit_wage.gt(0) & exit_wage.le(100)
        valid_start_wage += int(valid_sw.sum())
        valid_exit_wage += int(valid_ew.sum())
        update_counter(
            wage_hist, start_wage[valid_sw].round(2).astype("string")
        )
        for year in ANALYSIS_YEARS:
            wm = valid_sw & start_year.eq(year)
            if wm.any():
                update_counter(
                    wage_by_start_year[year],
                    start_wage[wm].round(2).astype("string"),
                )

        pair = (
            status.eq("CO")
            & valid_sw
            & valid_ew
            & exit_dt.notna()
            & (exit_dt <= AS_OF)
        )
        if pair.any():
            ratios = (
                (exit_wage[pair] - start_wage[pair]) / start_wage[pair]
            ).replace([np.inf, -np.inf], np.nan).dropna()
            completed_wage_pairs += int(len(ratios))
            completed_wage_declines += int((ratios < 0).sum())
            update_counter(
                uplift_hist,
                ratios.clip(-1, 10).round(3).astype("string"),
            )

        if chunks % 5 == 0:
            print(f"scanned {rows:,} rows", flush=True)

    status_rows = []
    for code, count in status_counts.most_common():
        status_rows.append(
            {
                "status_code": code,
                "label": CODE_LABELS["status"].get(code, "Unclassified"),
                "count": count,
                "share": count / rows,
            }
        )
    write_rows(OUT / "status_counts.csv", status_rows)

    starts_rows = []
    for year in sorted(
        int(y) for y in start_year_counts if str(y).isdigit()
    ):
        starts_rows.append(
            {
                "start_year": year,
                "new_apprentices": start_year_counts[str(year)],
            }
        )
    write_rows(OUT / "starts_by_year.csv", starts_rows)

    age_rows = [
        {"age": int(age), "count": count}
        for age, count in sorted(age_hist.items(), key=lambda x: int(x[0]))
    ]
    write_rows(OUT / "age_distribution.csv", age_rows)

    age_year_rows = []
    for year in ANALYSIS_YEARS:
        counter = Counter(
            {
                age: count
                for (yr, age), count in age_by_start_year.items()
                if yr == str(year)
            }
        )
        if counter:
            age_year_rows.append(
                {
                    "start_year": year,
                    "count": sum(counter.values()),
                    "median_age": weighted_quantile(counter, 0.5),
                    "p25_age": weighted_quantile(counter, 0.25),
                    "p75_age": weighted_quantile(counter, 0.75),
                }
            )
    write_rows(OUT / "age_by_start_year.csv", age_year_rows)

    demo_rows = []
    for year in ANALYSIS_YEARS:
        sex = Counter(
            {
                code: count
                for (yr, code), count in sex_by_start_year.items()
                if yr == str(year)
            }
        )
        identified_sex = sum(sex[c] for c in ("1", "2", "3"))
        ethnicity = Counter(
            {
                code: count
                for (yr, code), count in ethnicity_by_start_year.items()
                if yr == str(year)
            }
        )
        identified_eth = ethnicity["1"] + ethnicity["2"]
        race = Counter(
            {
                code: count
                for (yr, code), count in race_by_start_year.items()
                if yr == str(year)
            }
        )
        identified_race = sum(
            race[c] for c in ("1", "2", "3", "4", "5", "7")
        )
        demo_rows.append(
            {
                "start_year": year,
                "sex_known_n": identified_sex,
                "female_share_identified": pct(sex["2"], identified_sex),
                "nonbinary_share_identified": pct(
                    sex["3"], identified_sex
                ),
                "sex_missing_or_unidentified": int(
                    start_year_counts[str(year)] - identified_sex
                ),
                "ethnicity_known_n": identified_eth,
                "hispanic_share_identified": pct(
                    ethnicity["1"], identified_eth
                ),
                "race_known_n": identified_race,
                "black_share_identified": pct(race["3"], identified_race),
                "asian_share_identified": pct(race["4"], identified_race),
                "multirace_share_identified": pct(
                    race["7"], identified_race
                ),
            }
        )
    write_rows(OUT / "demographics_by_start_year.csv", demo_rows)

    wage_year_rows = []
    for year in ANALYSIS_YEARS:
        counter = wage_by_start_year[year]
        if counter:
            wage_year_rows.append(
                {
                    "start_year": year,
                    "valid_wage_records": sum(counter.values()),
                    "p25_starting_wage": weighted_quantile(counter, 0.25),
                    "median_starting_wage": weighted_quantile(counter, 0.5),
                    "p75_starting_wage": weighted_quantile(counter, 0.75),
                }
            )
    write_rows(OUT / "starting_wage_by_start_year.csv", wage_year_rows)

    outcome_rows = []
    for year in range(2010, 2026):
        counts = Counter(
            {
                code: count
                for (yr, code), count in outcome_by_start_year.items()
                if yr == str(year)
            }
        )
        resolved = counts["CO"] + counts["CA"]
        total = sum(counts.values())
        outcome_rows.append(
            {
                "start_year": year,
                "cohort_records": total,
                "completed_current_status": counts["CO"],
                "cancelled_current_status": counts["CA"],
                "still_active_or_other": total - resolved,
                "resolved_exits": resolved,
                "completion_share_among_resolved_exits": pct(
                    counts["CO"], resolved
                ),
                "note": (
                    "Exploratory current-status share, not an official "
                    "DOL completion rate"
                ),
            }
        )
    write_rows(
        OUT / "resolved_outcomes_by_start_cohort.csv", outcome_rows
    )

    top_occ_rows = [
        {"occupation_title": key, "new_apprentices_fy2025": value}
        for key, value in fy_occupation.most_common(30)
    ]
    write_rows(OUT / "top_occupations_fy2025.csv", top_occ_rows)
    modal_title = {}
    for (soc, title), count in fy_soc_title.items():
        if soc not in modal_title or count > modal_title[soc][1]:
            modal_title[soc] = (title, count)
    top_soc_rows = [
        {
            "onet_soc_cd": soc,
            "representative_title": modal_title.get(soc, ("", 0))[0],
            "new_apprentices_fy2025": count,
        }
        for soc, count in fy_soc.most_common(30)
    ]
    write_rows(OUT / "top_occupations_by_soc_fy2025.csv", top_soc_rows)
    state_rows = [
        {"program_state": key, "new_apprentices_fy2025": value}
        for key, value in fy_state.most_common()
    ]
    write_rows(
        OUT / "new_apprentices_by_program_state_fy2025.csv", state_rows
    )

    program_rows = []
    all_program_ids = (
        set(fy_program_new) | set(fy_program_active) | set(fy_program_exiters)
    )
    for ps in all_program_ids:
        program_rows.append(
            {
                "ps_id": ps,
                "program_name": prog_name.get(ps, ""),
                "program_state": prog_state.get(ps, ""),
                "program_status": prog_status.get(ps, ""),
                "union_or_cba_flag": prog_union.get(ps, ""),
                "new_apprentices_fy2025": fy_program_new[ps],
                "active_apprentices_fy2025": fy_program_active[ps],
                "exiters_fy2025": fy_program_exiters[ps],
            }
        )
    write_rows(
        OUT / "program_kpis_fy2025.csv",
        sorted(
            program_rows,
            key=lambda row: row["active_apprentices_fy2025"],
            reverse=True,
        ),
    )

    quality_rows = [
        {
            "field": col,
            "null_count": nulls[col],
            "null_rate": nulls[col] / rows,
        }
        for col in USECOLS
    ]
    write_rows(OUT / "field_completeness.csv", quality_rows)

    recent_demo = next(
        (row for row in demo_rows if row["start_year"] == 2025), {}
    )
    age_2025 = next(
        (row for row in age_year_rows if row["start_year"] == 2025), {}
    )
    wage_2025 = next(
        (row for row in wage_year_rows if row["start_year"] == 2025), {}
    )
    summary = {
        "source": str(source),
        "source_bytes": source.stat().st_size,
        "data_as_of": str(AS_OF.date()),
        "rows": rows,
        "columns_in_source": 78,
        "duplicate_header": "APPR_STATUS_REASON appears twice",
        "duplicate_appr_id_rows": duplicate_appr_ids,
        "date_range": {
            "start_min": None if min_start is None else str(min_start.date()),
            "start_max": None if max_start is None else str(max_start.date()),
            "exit_min": None if min_exit is None else str(min_exit.date()),
            "exit_max": None if max_exit is None else str(max_exit.date()),
            "future_start_dates": future_start_dates,
            "future_exit_dates": future_exit_dates,
            "exit_before_start": exit_before_start,
            "malformed_start_dates": malformed_dates["start"],
            "malformed_exit_dates": malformed_dates["exit"],
        },
        "official_fy2025_kpis": {
            "period_start": str(FY_START.date()),
            "period_end": str(FY_END.date()),
            "active_apprentices": official_active,
            "new_apprentices": official_new,
            "exiters": official_exiters,
            "completed_exiters": official_completed,
            "cancelled_exiters": official_cancelled,
            "total_apprentices_served": official_active + official_exiters,
        },
        "quality": {
            "invalid_age_values": invalid_age,
            "age_cohort_comparable": age_cohort_comparable,
            "age_cohort_mismatches": age_cohort_mismatch,
            "age_cohort_mismatch_rate": pct(
                age_cohort_mismatch, age_cohort_comparable
            ),
            "zero_or_negative_start_wages": zero_or_negative_start_wage,
            "start_wages_above_100": implausible_start_wage,
            "valid_hourly_start_wages_0_to_100": valid_start_wage,
            "valid_exit_wages_0_to_100": valid_exit_wage,
            "rows_not_mapped_to_program_state": unmatched_program_rows,
            "starting_wage_indicator_counts": dict(starting_wage_ind_counts),
        },
        "wages": {
            "starting_wage_p25": weighted_quantile(wage_hist, 0.25),
            "starting_wage_median": weighted_quantile(wage_hist, 0.5),
            "starting_wage_p75": weighted_quantile(wage_hist, 0.75),
            "completed_records_with_valid_wage_pair": completed_wage_pairs,
            "completed_records_with_recorded_wage_decline": (
                completed_wage_declines
            ),
            "median_nominal_wage_change": weighted_quantile(
                uplift_hist, 0.5
            ),
        },
        "recent_story_metrics": {
            "median_age_for_2025_starts": age_2025.get("median_age"),
            "female_share_among_identified_2025_starts": (
                recent_demo.get("female_share_identified")
            ),
            "median_recorded_starting_wage_for_2025_starts": (
                wage_2025.get("median_starting_wage")
            ),
        },
        "program_file": program_meta,
        "unclassified_status_codes": sorted(
            code for code in status_counts if code not in CODE_LABELS["status"]
        ),
        "notes": [
            "AGE_AT_START is marked deprecated in the official data dictionary.",
            "Wage summaries use records explicitly flagged hourly; values are "
            "nominal and are not inflation-adjusted.",
            "Completion share among resolved exits is exploratory and is not "
            "an official DOL completion rate.",
            "All outputs are aggregate; no individual apprentice rows are written.",
        ],
    }
    (OUT / "profile_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    recent_starts = [
        row
        for row in starts_rows
        if row["start_year"] in ANALYSIS_YEARS
    ]
    save_line_chart(
        recent_starts,
        "start_year",
        "new_apprentices",
        "Apprenticeship starts remained near a record high in 2025",
        "Full calendar years; denied/incomplete registrations excluded",
        "New apprentice records",
        OUT / "starts_trend_2015_2025.png",
    )
    save_line_chart(
        demo_rows,
        "start_year",
        "female_share_identified",
        "Women are a growing share of new apprentices",
        "Share among identified records; full calendar years 2015-2025",
        "Female share",
        OUT / "female_share_trend_2015_2025.png",
        percent=True,
    )
    save_line_chart(
        age_year_rows,
        "start_year",
        "median_age",
        "The typical apprentice starts in their mid-20s",
        "Median recorded age at start; exact age is deprecated and should be "
        "used cautiously",
        "Median age",
        OUT / "median_age_trend_2015_2025.png",
    )
    save_line_chart(
        wage_year_rows,
        "start_year",
        "median_starting_wage",
        "Recorded hourly starting wages increased in nominal dollars",
        "Median records flagged hourly; non-positive and values above $100 "
        "excluded; not inflation-adjusted; full calendar years 2015-2025",
        "Median reported wage ($)",
        OUT / "starting_wage_trend_2015_2025.png",
    )
    save_bar_chart(
        top_soc_rows[:10][::-1],
        "representative_title",
        "new_apprentices_fy2025",
        "The largest apprenticeship occupations",
        "New apprentices during FY2025 using DOL's KPI definition",
        OUT / "top_occupations_fy2025.png",
    )

    print(
        json.dumps(
            {
                "output_dir": str(OUT),
                "rows": rows,
                "official_fy2025_kpis": summary["official_fy2025_kpis"],
                "recent_story_metrics": summary["recent_story_metrics"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--chunk-size", type=int, default=100_000)
    args = parser.parse_args()
    main(args.source, args.chunk_size)
