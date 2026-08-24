"""
RAPIDS round 1, Task 1: define the real IBEW construction JATC universe from the
DOL RAPIDS extract, then join it to the 244 (245 on disk) inside-wireman locals in
out/locals.csv.

Owns: raw/rapids/, out/rapids_*, this file. Does not touch compute_status.py,
statement_evidence.py, window_rules.py, monitor.py, archive/, build scripts, page
templates, or build output. No network calls. apprentices.csv is not read here --
this task never needed it.

Corrects two errors from the original quick read, plus a third found empirically
while building this:

1. UNION_Y_N=1 is not the IBEW/JATC universe -- it includes any employer covered by
   a union CBA (in-house maintenance electricians at unionized plants). The real
   sponsor-type marker is SPON_UNIONLABOR ("is the sponsor a union or labor
   organization?"), a separate field.

2. SEL_PROCS is empty across the corrected universe too (0 of 218 in an earlier
   pass) -- do not build on it. IS_SEL_PROC has a handful of true values with no
   text behind them; not usable either.

3. SPON_UNIONLABOR is itself unreliable in a specific set of states (measured: the
   ratio of SPON_UNIONLABOR=1 programs to programs whose name literally contains
   "IBEW"/"JATC" collapses to near-zero in OR, WA, NY, NC, NM, SD, and partially in
   CO, OH, MA, UT, CT, MT, MS, OK, ID, WY). A hard filter on that field alone
   silently drops real JATCs in those states, including LU 3 New York and LU 46
   Seattle. The fix below is a hybrid: use SPON_UNIONLABOR where it's reliable, and
   fall back to UNION_Y_N + a name check where it isn't.

LOCAL_AREA (on both programs.csv and occ-prog-bridge.csv) is NOT a union local
number field -- it's a DOL workforce-area code (LA I-VII, "Statewide"), populated
on only 475 of 130,730 programs. Do not join on it.

IS_NGS / NGS_ID is populated on only ~14% of candidate programs even after the
universe is corrected. Not reliable enough to use as a filter.
"""

import csv
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "rapids"
OUT = ROOT / "out"

ELECTRICIAN_ONET = "4721110"  # 47-2111.00, normalized (dots/dashes stripped)

NON_IBEW_KEYWORDS = [
    "UAW", "IUOE", "OPERATING ENGINEER", "STEELWORKER", "IAMAW", "MACHINIST",
    "CARPENTER", "JOHN DEERE", "GENERAL MOTORS", "ASSOCIATED BUILDERS",
    "INDEPENDENT ELECTRICAL CONTRACTOR", "TEST ", "BRICKLAYER", "CEMENT MASON",
    # Round-3: other unions / single employers that pass the broadened name test
    "UNITED ELECTRICAL WORKERS", "MOSAIC", "AMPINE",
]

# Round-3 universe rule. Two tiers of name evidence:
#   STRONG -- unambiguous IBEW/JATC markers. Admitted on the name alone, because
#     UNION_Y_N is not reliably set even on obvious IBEW programs (e.g.
#     "IBEW Local 300" and "New Orleans Electrical JATC" both have UNION_Y_N=0).
#   WEAK -- names that describe a joint/area electrical training body but could
#     also be a single employer ("Austin Electrical"). These require UNION_Y_N=1.
# Round 2 required a STRONG signal for everything, which wrongly dropped 22 real
# JATCs (Hawaii, Miami, Omaha, Owensboro, Puget Sound, St Paul, Alaska, Wichita,
# Orange County, San Mateo, and every "... Electrical Training Alliance", which
# is the IBEW/NECA national training organization's own name). Dropping the name
# test entirely and using UNION_Y_N alone is worse: it admits 530 programs
# including Amtrak, City of Detroit, and Associated Builders & Contractors.
STRONG_NAME_RE = (
    r"IBEW|NECA|JATC|\bJAC\b|\bJEATC\b"
    r"|J\.\s*A\.\s*T\.\s*C|J\.\s*E\.\s*A\.\s*T\.\s*C"
)
WEAK_NAME_RE = (
    r"JOINT\s+APPRENTICE|JOINT\s+ELECTRIC"
    r"|APPRENTICESHIP\s+(?:AND|&)\s+TRAINING"
    r"|ELECTRICAL\s+TRAINING\s+(?:ALLIANCE|TRUST|CENTER|CENTRE|FUND)"
    r"|ELECTRICIANS\b|ELECTRICAL\s+INDUSTRY|ELECTRICAL\s+WORKERS"
)

STATUS_RANK = {
    "Registered": 0, "Re-Instated": 1, "Suspended": 2, "In Progress": 3,
    "Cancelled": 4, "Deleted": 5,
}

FUZZY_MATCH_THRESHOLD = 75

blockers = []


def log_blocker(stage, message):
    blockers.append({"stage": stage, "message": message})
    print(f"[blocker] {stage}: {message}", file=sys.stderr)


def norm_onet(x):
    if pd.isna(x):
        return None
    return str(x).replace(".", "").replace("-", "")[:7]


def extract_lu(name):
    m = re.search(r"(?:LOCAL|LU|L\.U\.|IBEW)\s*#?\s*(\d{1,4})", str(name).upper())
    return m.group(1) if m else None


def is_non_ibew(name):
    n = str(name).upper()
    return any(k in n for k in NON_IBEW_KEYWORDS)


def token_sort_ratio(a, b):
    """Cheap stand-in for rapidfuzz.fuzz.token_sort_ratio using stdlib difflib."""
    ta = " ".join(sorted(str(a).upper().split()))
    tb = " ".join(sorted(str(b).upper().split()))
    return SequenceMatcher(None, ta, tb).ratio() * 100


def build_universe():
    prog_path = RAW / "programs.csv"
    bridge_path = RAW / "occ-prog-bridge.csv"
    addl_path = RAW / "additional program info.csv"

    for p in (prog_path, bridge_path, addl_path):
        if not p.exists():
            log_blocker("build_universe", f"missing required file: {p}")
            raise SystemExit(1)

    prog = pd.read_csv(prog_path, dtype=str, low_memory=False)
    bridge = pd.read_csv(bridge_path, dtype=str, low_memory=False)
    addl = pd.read_csv(addl_path, dtype=str, low_memory=False)
    addl.columns = [c.strip().lstrip("﻿") for c in addl.columns]

    bridge["onet_norm"] = bridge["ONET_SOC_CD"].apply(norm_onet)
    elec_ps_ids = set(bridge[bridge["onet_norm"] == ELECTRICIAN_ONET]["PS_ID"].unique())

    merged = prog[prog["PS_ID"].isin(elec_ps_ids)].merge(addl, on="PS_ID", how="left")

    # Round-2 fix: SPON_UNIONLABOR=1 alone is not IBEW evidence -- it's how
    # "Solentricx, Inc." (a non-IBEW union electrical contractor) got into the
    # candidate set and was then displayed as Local 716 Houston's own number.
    # A program now qualifies only on an affirmative IBEW/JATC signal in its
    # own name: literal IBEW/JATC/JAC, or a recognizable "Local ###" /
    # "LU ###" number pattern (extract_lu below). SPON_UNIONLABOR/UNION_Y_N
    # are no longer part of the qualification test at all -- they were the
    # unreliable half of the old OR, and requiring the name signal already
    # subsumes the cases where they were correct.
    name_has_ibew_jatc = merged["PROG_NAME"].str.contains(
        STRONG_NAME_RE, case=False, na=False, regex=True
    )
    name_weak_signal = merged["PROG_NAME"].str.contains(
        WEAK_NAME_RE, case=False, na=False, regex=True
    )
    has_lu_number_pattern = merged["PROG_NAME"].apply(extract_lu).notna()
    union_yn = merged["UNION_Y_N"] == "1"
    strong = name_has_ibew_jatc | has_lu_number_pattern
    candidate_mask = strong | (name_weak_signal & union_yn)

    # Reporting only, not used to filter: what the old (round-1) rule would
    # have admitted, so a diff of dropped names can be eyeballed for false
    # negatives (a name-matched local's program disappearing would mean this
    # rule is too tight).
    old_union_sponsor = merged["SPON_UNIONLABOR"] == "1"
    old_union_yn = merged["UNION_Y_N"] == "1"
    old_candidate_mask = old_union_sponsor | (old_union_yn & name_has_ibew_jatc)

    def _final_clean(mask):
        c = merged[mask].copy()
        c = c[c["IS_MULTI_EMP"] == "1"]
        c["likely_non_ibew"] = c["PROG_NAME"].apply(is_non_ibew)
        c = c[~c["likely_non_ibew"]].copy()
        c["rank"] = c["PROG_STATUS"].map(STATUS_RANK).fillna(9)
        c = c.sort_values("rank").drop_duplicates(subset=["PROG_NAME", "PROG_CITY", "PROG_STATE"], keep="first")
        return c

    old_clean = _final_clean(old_candidate_mask)
    new_clean_preview = _final_clean(candidate_mask)
    dropped = old_clean[~old_clean["PS_ID"].isin(new_clean_preview["PS_ID"])][
        ["PS_ID", "PROG_NAME", "PROG_CITY", "PROG_STATE", "SPON_UNIONLABOR", "UNION_Y_N"]
    ].drop_duplicates()
    dropped.to_csv(OUT / "rapids_universe_dropped_round2.csv", index=False)

    cset = merged[candidate_mask].copy()
    cset = cset[cset["IS_MULTI_EMP"] == "1"]

    cset["likely_non_ibew"] = cset["PROG_NAME"].apply(is_non_ibew)
    clean = cset[~cset["likely_non_ibew"]].copy()

    clean["lu_guess"] = clean["PROG_NAME"].apply(extract_lu)
    clean["rank"] = clean["PROG_STATUS"].map(STATUS_RANK).fillna(9)
    clean = (
        clean.sort_values("rank")
        .drop_duplicates(subset=["PROG_NAME", "PROG_CITY", "PROG_STATE"], keep="first")
        .reset_index(drop=True)
    )

    excluded = cset[cset["likely_non_ibew"]][["PROG_NAME", "PROG_CITY", "PROG_STATE"]]
    excluded.drop_duplicates().to_csv(OUT / "rapids_excluded_non_ibew.csv", index=False)

    universe_diff = {
        "old_clean_count": len(old_clean),
        "new_clean_count": len(clean),
        "dropped": dropped,
    }
    return clean, universe_diff


# Round-3: a local often registers several programs, one per classification
# (inside wireman, residential, commercial wireman, VDV, sound & comm). The join
# used to keep whichever sorted first, which is how Local 1 St. Louis ended up
# reporting its "Commercial Wireman" program's intake of 3 and Local 124 Kansas
# City its residential program's 6. The site covers inside wireman, and an
# unqualified JATC name is the inside wireman program, so prefer that.
CLASSIFICATION_QUALIFIERS = [
    "RESIDENTIAL", "/RES", " RES ", "-RES", "COMMERCIAL", "VDV", "SOUND",
    "TELECOM", "TELEDATA", "LINEMAN", "OUTSIDE", "LOW VOLTAGE", "INSTALLER",
]


def classification_rank(name):
    """0 = unqualified (inside wireman), 1 = classification-specific."""
    n = f" {str(name).upper()} "
    return 1 if any(q in n for q in CLASSIFICATION_QUALIFIERS) else 0


def pick_primary(cands):
    """Choose the program representing the local; return (chosen, others, rule).

    Order: live status first, then inside-wireman (unqualified name), then the
    shorter name. Status matters most: five locals (Boston 103, 110, 7, 96, 649)
    were matched to Cancelled registrations and reported 0 apprentices as fact.
    A cancelled registration is not the local's current program.
    """
    c = cands.copy()
    c["_st"] = c["PROG_STATUS"].map(STATUS_RANK).fillna(9)
    c["_cls"] = c["PROG_NAME"].apply(classification_rank)
    c["_len"] = c["PROG_NAME"].astype(str).str.len()
    c = c.sort_values(["_st", "_cls", "_len"], kind="mergesort")
    if len(c) == 1:
        rule = "sole_program"
    elif c.iloc[0]["_st"] < c.iloc[1]["_st"]:
        rule = "live_status"
    elif c.iloc[0]["_cls"] == 0:
        rule = "unqualified_name"
    else:
        rule = "shortest_name_all_qualified"
    return c.iloc[0], c.iloc[1:], rule


def join_to_locals(clean):
    cld_path = OUT / "complete_lus_derived.csv"
    locals_path = OUT / "locals.csv"
    for p in (cld_path, locals_path):
        if not p.exists():
            log_blocker("join_to_locals", f"missing required file: {p}")
            raise SystemExit(1)

    cld = pd.read_csv(cld_path, dtype=str, low_memory=False)
    locals_df = pd.read_csv(locals_path, dtype=str, low_memory=False)
    target = cld.merge(locals_df, on=["local_union_id", "lu_number"], how="left")

    results, secondary = [], []
    for _, loc in target.iterrows():
        lu, state, city = loc["lu_number"], loc["primary_state"], loc["primary_city"]

        lu_matches = clean[(clean["lu_guess"] == lu) & (clean["PROG_STATE"] == state)]
        if len(lu_matches):
            p, others, rule = pick_primary(lu_matches)
            for _, o in others.iterrows():
                secondary.append({
                    "lu_number": lu, "match_type": "lu_number_match",
                    "rapids_ps_id": o["PS_ID"], "rapids_name": o["PROG_NAME"],
                    "rapids_city": o["PROG_CITY"], "rapids_state": o["PROG_STATE"],
                    "reason": "not_selected_as_primary",
                })
            results.append({
                "lu_number": lu, "local_city": city, "local_state": state,
                "match_type": "lu_number_match", "rapids_ps_id": p["PS_ID"],
                "rapids_name": p["PROG_NAME"], "rapids_city": p["PROG_CITY"],
                "rapids_state": p["PROG_STATE"], "rapids_status": p["PROG_STATUS"],
                "score": 100, "n_programs": len(lu_matches), "selection_rule": rule,
            })
            continue

        cands = clean[clean["PROG_STATE"] == state]
        if len(cands) == 0:
            results.append({
                "lu_number": lu, "local_city": city, "local_state": state,
                "match_type": "no_state_candidates", "rapids_ps_id": None,
                "rapids_name": None, "rapids_city": None, "rapids_state": None,
                "rapids_status": None, "score": 0,
            })
            continue

        best_score, best_idx = -1, None
        for idx, c in cands.iterrows():
            s = token_sort_ratio(city, c["PROG_CITY"])
            if s > best_score:
                best_score, best_idx = s, idx

        if best_score >= FUZZY_MATCH_THRESHOLD:
            tied = cands[cands["PROG_CITY"].apply(
                lambda cc: token_sort_ratio(city, cc) == best_score)]
            p, others, rule = pick_primary(tied)
            for _, o in others.iterrows():
                secondary.append({
                    "lu_number": lu, "match_type": "city_fuzzy_match",
                    "rapids_ps_id": o["PS_ID"], "rapids_name": o["PROG_NAME"],
                    "rapids_city": o["PROG_CITY"], "rapids_state": o["PROG_STATE"],
                    "reason": "tied_on_city_not_selected",
                })
            results.append({
                "n_programs": len(tied), "selection_rule": rule,
                "lu_number": lu, "local_city": city, "local_state": state,
                "match_type": "city_fuzzy_match", "rapids_ps_id": p["PS_ID"],
                "rapids_name": p["PROG_NAME"], "rapids_city": p["PROG_CITY"],
                "rapids_state": p["PROG_STATE"], "rapids_status": p["PROG_STATUS"],
                "score": round(best_score, 1),
            })
        else:
            results.append({
                "lu_number": lu, "local_city": city, "local_state": state,
                "match_type": "no_match", "rapids_ps_id": None,
                "rapids_name": None, "rapids_city": None, "rapids_state": None,
                "rapids_status": None, "score": round(best_score, 1),
            })

    pd.DataFrame(secondary).to_csv(OUT / "rapids_locals_join_secondary.csv", index=False)
    print(f"  multi-program locals: "
          f"{sum(1 for r in results if (r.get('n_programs') or 1) > 1)}; "
          f"{len(secondary)} secondary programs held aside")
    return pd.DataFrame(results)


def main():
    print(f"Reading RAPIDS extract from {RAW}")
    clean, universe_diff = build_universe()
    print(f"Candidate JATC universe: {len(clean)} programs "
          f"({(clean['PROG_STATUS'] == 'Registered').sum()} Registered)")

    print()
    print(f"Round-2 universe tightening (affirmative IBEW name signal required, "
          f"SPON_UNIONLABOR alone no longer sufficient):")
    print(f"  old rule final universe: {universe_diff['old_clean_count']} programs")
    print(f"  new rule final universe: {universe_diff['new_clean_count']} programs")
    dropped = universe_diff["dropped"]
    print(f"  dropped: {len(dropped)} programs (see out/rapids_universe_dropped_round2.csv)")
    if len(dropped):
        for _, r in dropped.iterrows():
            print(f"    {r['PROG_NAME']} -- {r['PROG_CITY']}, {r['PROG_STATE']} "
                  f"(SPON_UNIONLABOR={r['SPON_UNIONLABOR']}, UNION_Y_N={r['UNION_Y_N']})")

    clean.to_csv(OUT / "rapids_universe.csv", index=False)

    join_result = join_to_locals(clean)
    join_result.to_csv(OUT / "rapids_locals_join.csv", index=False)

    counts = join_result["match_type"].value_counts()
    matched = join_result["match_type"].isin(["lu_number_match", "city_fuzzy_match"]).sum()
    total = len(join_result)
    print(f"Matched {matched} / {total} locals ({matched/total:.1%})")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    if blockers:
        with open(OUT / "rapids_blockers.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["stage", "message"])
            w.writeheader()
            w.writerows(blockers)
        print(f"Wrote {len(blockers)} blocker(s) to out/rapids_blockers.csv")

    print()
    print("Files touched:")
    print("  out/rapids_universe.csv")
    print("  out/rapids_locals_join.csv")
    print("  out/rapids_excluded_non_ibew.csv")
    if blockers:
        print("  out/rapids_blockers.csv")


if __name__ == "__main__":
    main()
