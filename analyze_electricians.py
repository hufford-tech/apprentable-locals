"""Targeted analysis of electrician apprentices in the RAPIDS public-use file.

Electricians are defined by O*NET-SOC 47-2111.00. Line maintainers and related
electrical occupations remain separate. Only aggregate outputs are written.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import analyze_apprentices as base


ROOT = Path(__file__).resolve().parent
SOURCE = (
    Path.home() / "Downloads" / "Apprentice Data pull 8.18.26" / "apprentices.csv"
)
PROGRAMS = ROOT / "raw" / "rapids" / "programs.csv"
PROGRAM_INFO = ROOT / "raw" / "rapids" / "additional program info.csv"
ALL_OUT = ROOT / "out" / "apprentices_analysis"
OUT = ALL_OUT / "electricians"

SOC = "47-2111.00"
AS_OF = pd.Timestamp("2026-08-17")
FY_START = pd.Timestamp("2024-10-01")
FY_END = pd.Timestamp("2025-09-30")
DENIED = {"DL", "DR", "IR", "PR", "DU"}
ACTIVE = {"RE", "RI", "SU", "TR", "UP"}
EXITED = {"CA", "CO"}
YEARS = list(range(2015, 2026))

USECOLS = [
    "APPR_NUMBER",
    "PS_ID",
    "APPR_STATUS_CD",
    "START_DT",
    "EXIT_WAGE_DT",
    "STARTING_WAGE",
    "EXIT_WAGE",
    "STARTINGWAGEIND",
    "AGE_AT_START",
    "SEX_CD",
    "ETHNICITY_CD",
    "RACE_CD",
    "EDUCATION_CD",
    "OCCUPATION_TITLE",
    "ONET_SOC_CD",
]


def program_category(name: str, single: str, multi: str, union: str, cba: str) -> str:
    upper = (name or "").upper()
    if "UNITED SERVICES MILITARY APPRENTICESHIP" in upper or "USMAP" in upper:
        return "USMAP"
    joint_name = bool(
        re.search(
            r"\b(?:IBEW|NECA|JATC|JATF|JAC|ELECTRICAL TRAINING|ELECTRICAL WORKERS)\b",
            upper,
        )
    )
    if multi == "1" and (union == "1" or cba == "1" or joint_name):
        return "Multi-employer union/CBA or joint-training signal"
    if single == "1":
        return "Single-employer program"
    if multi == "1":
        return "Other multi-employer program"
    return "Other or unknown"


def load_program_maps():
    programs = pd.read_csv(PROGRAMS, dtype="string", low_memory=False)
    programs.columns = [str(c).replace("\ufeff", "") for c in programs.columns]
    programs["PS_ID"] = programs["PS_ID"].str.strip()
    programs = programs.drop_duplicates("PS_ID", keep="first")

    info = pd.read_csv(PROGRAM_INFO, dtype="string", low_memory=False)
    info.columns = [str(c).replace("\ufeff", "") for c in info.columns]
    info["PS_ID"] = info["PS_ID"].str.strip()
    info = info.drop_duplicates("PS_ID", keep="first")
    merged = programs.merge(
        info[["PS_ID", "IS_SINGLE_EMP", "IS_MULTI_EMP", "IS_CBA"]],
        on="PS_ID",
        how="left",
    )
    for col in [
        "PROG_STATE",
        "UNION_Y_N",
        "PROG_NAME",
        "PROG_STATUS",
        "IS_SINGLE_EMP",
        "IS_MULTI_EMP",
        "IS_CBA",
    ]:
        merged[col] = (
            merged[col]
            .fillna("")
            .astype("string")
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )
    maps = {
        col: merged.set_index("PS_ID")[col].astype(str).to_dict()
        for col in [
            "PROG_STATE",
            "UNION_Y_N",
            "PROG_NAME",
            "PROG_STATUS",
            "IS_SINGLE_EMP",
            "IS_MULTI_EMP",
            "IS_CBA",
        ]
    }
    category = {}
    for row in merged.itertuples(index=False):
        category[str(row.PS_ID)] = program_category(
            str(row.PROG_NAME),
            str(row.IS_SINGLE_EMP),
            str(row.IS_MULTI_EMP),
            str(row.UNION_Y_N),
            str(row.IS_CBA),
        )
    maps["CATEGORY"] = category
    return maps


def save_comparison_chart(
    rows: list[dict],
    left_key: str,
    right_key: str,
    left_label: str,
    right_label: str,
    title: str,
    subtitle: str,
    y_label: str,
    path: Path,
    percent: bool = False,
) -> None:
    width, height = 1400, 820
    im = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(im)
    navy, blue, orange, grid, text = (
        "#12304A",
        "#2477B3",
        "#D97A2B",
        "#D9E2E8",
        "#26343D",
    )
    d.text((75, 45), title, fill=navy, font=base.font(40, True))
    d.text((75, 100), subtitle, fill="#5A6B75", font=base.font(22))
    left, top, right, bottom = 125, 190, 1335, 700
    values_1 = [float(r[left_key]) for r in rows]
    values_2 = [float(r[right_key]) for r in rows]
    xs = [str(r["start_year"]) for r in rows]
    ymax = max(values_1 + values_2) * 1.15
    if ymax == 0:
        ymax = 1
    for i in range(6):
        yv = ymax * i / 5
        py = bottom - (bottom - top) * i / 5
        d.line((left, py, right, py), fill=grid, width=2)
        label = f"{yv:.0%}" if percent else f"{yv:,.0f}"
        d.text((left - 18, py), label, fill=text, font=base.font(18), anchor="rm")
    d.text((left, top - 32), y_label, fill=text, font=base.font(19, True), anchor="ls")
    points_1, points_2 = [], []
    for i, (v1, v2) in enumerate(zip(values_1, values_2)):
        px = left + (right - left) * i / max(1, len(rows) - 1)
        p1 = bottom - (bottom - top) * v1 / ymax
        p2 = bottom - (bottom - top) * v2 / ymax
        points_1.append((px, p1))
        points_2.append((px, p2))
        d.text((px, bottom + 18), xs[i], fill=text, font=base.font(18), anchor="ma")
    d.line(points_1, fill=blue, width=6, joint="curve")
    d.line(points_2, fill=orange, width=6, joint="curve")
    for px, py in points_1:
        d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=blue, outline="white")
    for px, py in points_2:
        d.rectangle((px - 6, py - 6, px + 6, py + 6), fill=orange, outline="white")
    legend_y = 150
    d.line((900, legend_y, 950, legend_y), fill=blue, width=6)
    d.text((960, legend_y), left_label, fill=text, font=base.font(18), anchor="lm")
    d.line((1120, legend_y, 1170, legend_y), fill=orange, width=6)
    d.text((1180, legend_y), right_label, fill=text, font=base.font(18), anchor="lm")
    d.text(
        (75, 770),
        "Source: U.S. DOL RAPIDS public-use extract, as of 2026-08-17. "
        "Aggregated by Apprentable analysis.",
        fill="#667780",
        font=base.font(17),
    )
    im.save(path)


def main(source: Path, chunk_size: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    maps = load_program_maps()
    all_starts = pd.read_csv(ALL_OUT / "starts_by_year.csv")
    all_demo = pd.read_csv(ALL_OUT / "demographics_by_start_year.csv")
    all_age = pd.read_csv(ALL_OUT / "age_by_start_year.csv")
    all_wage = pd.read_csv(ALL_OUT / "starting_wage_by_start_year.csv")
    all_summary = json.loads(
        (ALL_OUT / "profile_summary.json").read_text(encoding="utf-8")
    )

    total_electrician_rows = 0
    status_counts = Counter()
    title_counts = Counter()
    start_year_counts = Counter()
    age_by_year = Counter()
    sex_by_year = Counter()
    ethnicity_by_year = Counter()
    race_by_year = Counter()
    education_2025 = Counter()
    wage_by_year: dict[int, Counter] = defaultdict(Counter)
    outcome_by_year = Counter()
    fy_state = Counter()
    fy_program_new = Counter()
    fy_program_active = Counter()
    fy_program_exit = Counter()
    fy_category = Counter()
    fy_union = Counter()
    fy_cba = Counter()
    fy_single = Counter()
    fy_multi = Counter()
    fy_title = Counter()
    mature_category_outcomes = Counter()
    mature_union_outcomes = Counter()
    official_new = official_active = official_exiters = 0
    official_completed = official_cancelled = 0
    null_age = null_sex = null_wage = 0
    future_starts = 0

    reader = pd.read_csv(
        source,
        usecols=USECOLS,
        chunksize=chunk_size,
        low_memory=False,
        on_bad_lines="warn",
    )
    scanned = 0
    chunks = 0
    for chunk in reader:
        scanned += len(chunk)
        chunks += 1
        soc = base.clean_code(chunk["ONET_SOC_CD"])
        chunk = chunk.loc[soc.eq(SOC)].copy()
        if chunk.empty:
            if chunks % 5 == 0:
                print(f"scanned {scanned:,} source rows", flush=True)
            continue
        total_electrician_rows += len(chunk)

        status = base.clean_code(chunk["APPR_STATUS_CD"])
        base.update_counter(status_counts, status)
        titles = base.clean_title(chunk["OCCUPATION_TITLE"])
        base.update_counter(title_counts, titles)
        start_dt = pd.to_datetime(chunk["START_DT"], errors="coerce", format="mixed")
        exit_dt = pd.to_datetime(
            chunk["EXIT_WAGE_DT"], errors="coerce", format="mixed"
        )
        future_starts += int((start_dt > AS_OF).sum())
        start_year = start_dt.dt.year.astype("Int64")
        appr_number_ok = (
            chunk["APPR_NUMBER"].notna()
            & chunk["APPR_NUMBER"].astype("string").str.strip().ne("")
        )
        legitimate = appr_number_ok & ~status.isin(DENIED)
        valid_start = (
            legitimate
            & start_dt.notna()
            & (start_dt > pd.Timestamp("1900-01-01"))
            & (start_dt <= AS_OF)
        )
        base.update_counter(
            start_year_counts, start_year[valid_start].astype("string")
        )
        base.update_pair_counter(
            outcome_by_year,
            start_year[valid_start].astype("string"),
            status[valid_start],
        )

        ps_id = (
            pd.to_numeric(chunk["PS_ID"], errors="coerce")
            .astype("Int64")
            .astype("string")
        )
        states = ps_id.map(maps["PROG_STATE"]).replace("", pd.NA)
        unions = ps_id.map(maps["UNION_Y_N"]).replace("", pd.NA)
        cbas = ps_id.map(maps["IS_CBA"]).replace("", pd.NA)
        singles = ps_id.map(maps["IS_SINGLE_EMP"]).replace("", pd.NA)
        multis = ps_id.map(maps["IS_MULTI_EMP"]).replace("", pd.NA)
        categories = ps_id.map(maps["CATEGORY"]).replace("", pd.NA)

        fy_new = legitimate & start_dt.between(FY_START, FY_END, inclusive="both")
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
        base.update_counter(fy_state, states[fy_new])
        base.update_counter(fy_program_new, ps_id[fy_new])
        base.update_counter(fy_program_active, ps_id[fy_active])
        base.update_counter(fy_program_exit, ps_id[fy_exit])
        base.update_counter(fy_category, categories[fy_new])
        base.update_counter(fy_union, unions[fy_new])
        base.update_counter(fy_cba, cbas[fy_new])
        base.update_counter(fy_single, singles[fy_new])
        base.update_counter(fy_multi, multis[fy_new])
        base.update_counter(fy_title, titles[fy_new])

        age = pd.to_numeric(chunk["AGE_AT_START"], errors="coerce")
        sex = base.clean_code(chunk["SEX_CD"])
        ethnicity = base.clean_code(chunk["ETHNICITY_CD"])
        race = base.clean_code(chunk["RACE_CD"])
        education = base.clean_code(chunk["EDUCATION_CD"])
        wage = pd.to_numeric(chunk["STARTING_WAGE"], errors="coerce")
        wage_ind = base.clean_code(chunk["STARTINGWAGEIND"])
        null_age += int(age.isna().sum())
        null_sex += int(sex.isna().sum())
        null_wage += int(wage.isna().sum())

        for year in YEARS:
            mask = valid_start & start_year.eq(year)
            if not mask.any():
                continue
            valid_age = mask & age.between(14, 80, inclusive="both")
            base.update_pair_counter(
                age_by_year,
                start_year[valid_age].astype("string"),
                age[valid_age].round().astype("Int64").astype("string"),
            )
            base.update_pair_counter(
                sex_by_year,
                start_year[mask].astype("string"),
                sex[mask],
            )
            base.update_pair_counter(
                ethnicity_by_year,
                start_year[mask].astype("string"),
                ethnicity[mask],
            )
            base.update_pair_counter(
                race_by_year,
                start_year[mask].astype("string"),
                race[mask],
            )
            valid_wage = (
                mask & wage_ind.eq("H") & wage.gt(0) & wage.le(100)
            )
            base.update_counter(
                wage_by_year[year],
                wage[valid_wage].round(2).astype("string"),
            )
            if year == 2025:
                base.update_counter(education_2025, education[mask])

        mature = valid_start & start_year.between(2015, 2019)
        resolved = mature & status.isin(EXITED)
        base.update_pair_counter(
            mature_category_outcomes, categories[resolved], status[resolved]
        )
        base.update_pair_counter(
            mature_union_outcomes, unions[resolved], status[resolved]
        )

        if chunks % 5 == 0:
            print(f"scanned {scanned:,} source rows", flush=True)

    rows = []
    for year in YEARS:
        age_counter = Counter(
            {
                age: count
                for (yr, age), count in age_by_year.items()
                if yr == str(year)
            }
        )
        sex_counter = Counter(
            {
                code: count
                for (yr, code), count in sex_by_year.items()
                if yr == str(year)
            }
        )
        eth_counter = Counter(
            {
                code: count
                for (yr, code), count in ethnicity_by_year.items()
                if yr == str(year)
            }
        )
        identified_sex = sum(sex_counter[c] for c in ("1", "2", "3"))
        identified_eth = eth_counter["1"] + eth_counter["2"]
        all_start = int(
            all_starts.loc[
                all_starts["start_year"].eq(year), "new_apprentices"
            ].iloc[0]
        )
        all_demo_row = all_demo.loc[all_demo["start_year"].eq(year)].iloc[0]
        all_age_row = all_age.loc[all_age["start_year"].eq(year)].iloc[0]
        all_wage_row = all_wage.loc[all_wage["start_year"].eq(year)].iloc[0]
        rows.append(
            {
                "start_year": year,
                "electrician_starts": start_year_counts[str(year)],
                "all_starts": all_start,
                "electrician_share_of_all_starts": base.pct(
                    start_year_counts[str(year)], all_start
                ),
                "electrician_median_age": base.weighted_quantile(
                    age_counter, 0.5
                ),
                "all_median_age": float(all_age_row["median_age"]),
                "electrician_female_share_identified": base.pct(
                    sex_counter["2"], identified_sex
                ),
                "all_female_share_identified": float(
                    all_demo_row["female_share_identified"]
                ),
                "electrician_hispanic_share_identified": base.pct(
                    eth_counter["1"], identified_eth
                ),
                "all_hispanic_share_identified": float(
                    all_demo_row["hispanic_share_identified"]
                ),
                "electrician_hourly_start_wage_median": (
                    base.weighted_quantile(wage_by_year[year], 0.5)
                ),
                "all_hourly_start_wage_median": float(
                    all_wage_row["median_starting_wage"]
                ),
                "electrician_hourly_wage_n": sum(wage_by_year[year].values()),
            }
        )
    pd.DataFrame(rows).to_csv(OUT / "electrician_trends.csv", index=False)

    program_rows = []
    for ps in set(fy_program_new) | set(fy_program_active) | set(fy_program_exit):
        program_rows.append(
            {
                "ps_id": ps,
                "program_name": maps["PROG_NAME"].get(ps, ""),
                "program_state": maps["PROG_STATE"].get(ps, ""),
                "program_category": maps["CATEGORY"].get(ps, ""),
                "union_or_cba_flag": maps["UNION_Y_N"].get(ps, ""),
                "is_cba": maps["IS_CBA"].get(ps, ""),
                "is_single_employer": maps["IS_SINGLE_EMP"].get(ps, ""),
                "is_multi_employer": maps["IS_MULTI_EMP"].get(ps, ""),
                "new_electrician_apprentices_fy2025": fy_program_new[ps],
                "active_electrician_apprentices_fy2025": fy_program_active[ps],
                "electrician_exiters_fy2025": fy_program_exit[ps],
            }
        )
    program_rows.sort(
        key=lambda row: row["new_electrician_apprentices_fy2025"],
        reverse=True,
    )
    pd.DataFrame(program_rows).to_csv(
        OUT / "electrician_programs_fy2025.csv", index=False
    )

    pd.DataFrame(
        [
            {"program_state": key, "new_electrician_apprentices_fy2025": value}
            for key, value in fy_state.most_common()
        ]
    ).to_csv(OUT / "electrician_states_fy2025.csv", index=False)
    pd.DataFrame(
        [
            {"occupation_title": key, "new_electrician_apprentices_fy2025": value}
            for key, value in fy_title.most_common()
        ]
    ).to_csv(OUT / "electrician_titles_fy2025.csv", index=False)
    pd.DataFrame(
        [
            {"program_category": key, "new_electrician_apprentices_fy2025": value}
            for key, value in fy_category.most_common()
        ]
    ).to_csv(OUT / "electrician_program_structure_fy2025.csv", index=False)

    outcome_rows = []
    for category in sorted({key[0] for key in mature_category_outcomes}):
        completed = mature_category_outcomes[(category, "CO")]
        cancelled = mature_category_outcomes[(category, "CA")]
        outcome_rows.append(
            {
                "program_category": category,
                "completed_current_status": completed,
                "cancelled_current_status": cancelled,
                "resolved_records": completed + cancelled,
                "completion_share_among_resolved": base.pct(
                    completed, completed + cancelled
                ),
                "note": "Exploratory current-status share, not an official DOL completion rate",
            }
        )
    pd.DataFrame(outcome_rows).to_csv(
        OUT / "electrician_mature_outcomes_by_program_type.csv", index=False
    )

    education_rows = [
        {"education_code": code, "count_2025": count}
        for code, count in education_2025.most_common()
    ]
    pd.DataFrame(education_rows).to_csv(
        OUT / "electrician_education_2025.csv", index=False
    )

    summary = {
        "definition": "O*NET-SOC 47-2111.00 Electricians",
        "data_as_of": str(AS_OF.date()),
        "all_historical_electrician_rows": total_electrician_rows,
        "official_fy2025": {
            "new_electricians": official_new,
            "active_electricians": official_active,
            "electrician_exiters": official_exiters,
            "completed_exiters": official_completed,
            "cancelled_exiters": official_cancelled,
            "share_of_all_new_apprentices": base.pct(
                official_new,
                all_summary["official_fy2025_kpis"]["new_apprentices"],
            ),
        },
        "program_structure_fy2025": dict(fy_category),
        "union_flag_fy2025": dict(fy_union),
        "cba_flag_fy2025": dict(fy_cba),
        "single_employer_flag_fy2025": dict(fy_single),
        "multi_employer_flag_fy2025": dict(fy_multi),
        "future_electrician_start_dates": future_starts,
        "notes": [
            "Line maintainers (49-9051.00) are excluded.",
            "Program categories are descriptive heuristics, not audited IBEW classifications.",
            "Outcome shares are exploratory and are not official completion rates.",
            "Hourly wage summaries use only records explicitly marked H.",
        ],
    }
    (OUT / "electrician_profile.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    save_comparison_chart(
        rows,
        "electrician_female_share_identified",
        "all_female_share_identified",
        "Electricians",
        "All apprentices",
        "Women remain underrepresented among electrician starts",
        "Share among records with sex identified; full calendar years",
        "Female share",
        OUT / "electrician_female_share_comparison.png",
        percent=True,
    )
    save_comparison_chart(
        rows,
        "electrician_hourly_start_wage_median",
        "all_hourly_start_wage_median",
        "Electricians",
        "All apprentices",
        "Recorded electrician starting wages trail the overall median",
        "Median recorded hourly starting wage; nominal dollars",
        "Median hourly starting wage ($)",
        OUT / "electrician_wage_comparison.png",
    )
    indexed_rows = []
    e0 = rows[0]["electrician_starts"]
    a0 = rows[0]["all_starts"]
    for row in rows:
        indexed_rows.append(
            {
                "start_year": row["start_year"],
                "electrician_index": 100 * row["electrician_starts"] / e0,
                "all_index": 100 * row["all_starts"] / a0,
            }
        )
    save_comparison_chart(
        indexed_rows,
        "electrician_index",
        "all_index",
        "Electricians",
        "All apprentices",
        "Electrician apprenticeship grew faster than the system overall",
        "Calendar-year starts indexed to 2015 = 100",
        "Growth index",
        OUT / "electrician_growth_comparison.png",
    )
    base.save_bar_chart(
        [
            {
                "program_state": row["program_state"],
                "new_electrician_apprentices_fy2025": row[
                    "new_electrician_apprentices_fy2025"
                ],
            }
            for row in pd.read_csv(
                OUT / "electrician_states_fy2025.csv"
            ).query("program_state != 'ZA'").head(10).iloc[::-1].to_dict("records")
        ],
        "program_state",
        "new_electrician_apprentices_fy2025",
        "Texas leads electrician apprenticeship starts",
        "New electrician apprentices by program state, FY2025",
        OUT / "electrician_states_fy2025.png",
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--chunk-size", type=int, default=100_000)
    args = parser.parse_args()
    main(args.source, args.chunk_size)
