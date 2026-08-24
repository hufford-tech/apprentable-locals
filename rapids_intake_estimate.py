#!/usr/bin/env python3
"""Estimated annual apprentice intake for locals with no confirmed RAPIDS program.

Three tiers per local:
  confirmed      -- this local's own registered program, name-matched, live
                    status, reported to DOL. Shown exact.
  estimated      -- modelled from every real registered program we have,
                    scaled by this local's membership. Shown rounded.
  not_published  -- no membership figure to scale from.

Model: intake ~= median_intake * (members / median_members), capped.

Why membership and not jurisdiction population: measured. Leave-one-out error
on the 53 locals where the truth is known:

    bins by population (the previous model)   MdAPE 45.1%   p75 70.0%
    population, linear                        MdAPE 40.4%   p75 60.3%
    members, linear                           MdAPE 34.2%   p75 53.7%

Apprentice intake tracks how many electricians a local actually employs, not
how many people live in its jurisdiction. A local in a dense metro with few
signatory contractors takes few apprentices.

Why linear rather than a fitted curve: sublinear exponents were tested and are
worse (alpha 0.75 -> 40.6%, alpha 0.5 -> 55.2%). With 53 validation points a
fitted curve would overfit.

Why capped: linear scaling over-predicts the largest locals badly (Local 3, at
21,379 members, models to ~1072 against a real 315). The cap bounds that tail
without touching the median case.
"""

import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

# A bin/point estimate needs enough leave-one-out points before its error score
# means anything.
MIN_VALIDATION_N = 20

# Predictions are capped at this percentile of observed intake. Nothing in the
# reference set is bigger, so nothing above it is supportable.
CAP_PERCENTILE = 95


def pct(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def predict(members, med_members, med_intake, cap):
    if members <= 0 or med_members <= 0:
        return None
    return min(med_intake * (members / med_members), cap)


def main():
    fd = json.loads((OUT / "frontend_data.json").read_text(encoding="utf-8"))
    members_by_lu = {str(l["lu"]): float(l.get("members") or 0) for l in fd["locals"]}
    all_lus = [str(l["lu"]) for l in fd["locals"]]

    reference = []
    confirmed = {}
    period = ("", "")
    with open(OUT / "rapids_kpi_by_lu.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lu = str(r["lu_number"])
            intake = float(r["new_apprentices"])
            period = (r["period_start"], r["period_end"])
            m = members_by_lu.get(lu, 0)
            if m > 0:
                reference.append({"lu": lu, "members": m, "intake": intake})
            if r["match_type"] == "lu_number_match":
                confirmed[lu] = intake

    print(f"Reference set: {len(reference)} registered programs with a membership figure")
    print("Assumption: a city-matched program is a real program serving that market, "
          "not confirmed to belong to the local it matched to. It informs the model "
          "but is never displayed as that local's own figure.")

    intakes = sorted(x["intake"] for x in reference)
    med_members = statistics.median([x["members"] for x in reference])
    med_intake = statistics.median(intakes)
    cap = pct(intakes, CAP_PERCENTILE)
    print(f"\nModel: intake ~= {med_intake:.0f} * (members / {med_members:.0f}), "
          f"capped at {cap:.0f} (p{CAP_PERCENTILE} of observed intake)")
    print(f"  implies ~{med_intake / med_members:.3f} new apprentices per member per year")

    # ---- leave-one-out validation ------------------------------------------
    rows, errors = [], []
    for lu, actual in sorted(confirmed.items()):
        m = members_by_lu.get(lu, 0)
        if actual <= 0 or m <= 0:
            continue
        others = [x for x in reference if x["lu"] != lu]
        o_int = sorted(x["intake"] for x in others)
        p = predict(m, statistics.median([x["members"] for x in others]),
                    statistics.median(o_int), pct(o_int, CAP_PERCENTILE))
        if p is None:
            continue
        err = abs(p - actual) / actual * 100
        errors.append(err)
        rows.append({"lu_number": lu, "members": int(m), "actual": actual,
                     "predicted": round(p, 1), "abs_pct_error": round(err, 1)})

    with open(OUT / "rapids_intake_validation.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["lu_number", "members", "actual",
                                          "predicted", "abs_pct_error"])
        w.writeheader()
        w.writerows(rows)

    errors.sort()
    mdape = statistics.median(errors) if errors else 999.0
    print(f"\nLeave-one-out validation on {len(errors)} locals with a known figure:")
    print(f"  median absolute percentage error: {mdape:.1f}%")
    print(f"  25th / 75th percentile error: {pct(errors, 25):.1f}% / {pct(errors, 75):.1f}%")

    if len(errors) < MIN_VALIDATION_N:
        band, rounding = "insufficient_validation", None
        print(f"  Only {len(errors)} validation points -- not enough to publish on.")
    elif mdape < 35:
        band, rounding = "under_35", 5
        print("  Band: under 35% -- publish, rounded to the nearest 5.")
    elif mdape <= 60:
        band, rounding = "35_to_60", 10
        print("  Band: 35-60% -- publish, rounded to the nearest 10, strong caveat.")
    else:
        band, rounding = "over_60", None
        print("  Band: over 60% -- do not publish.")

    # ---- per-local output ---------------------------------------------------
    out_rows, tiers = [], {}
    for lu in all_lus:
        if lu in confirmed and confirmed[lu] > 0:
            tier, value = "confirmed", int(confirmed[lu])
        elif rounding and members_by_lu.get(lu, 0) > 0:
            p = predict(members_by_lu[lu], med_members, med_intake, cap)
            tier, value = "estimated", int(round(p / rounding) * rounding)
        else:
            tier, value = "not_published", None
        tiers[tier] = tiers.get(tier, 0) + 1
        out_rows.append({"lu_number": lu, "tier": tier, "value": value,
                         "members": int(members_by_lu.get(lu, 0)),
                         "period_start": period[0] if value is not None else "",
                         "period_end": period[1] if value is not None else ""})

    with open(OUT / "rapids_intake_estimate_by_lu.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["lu_number", "tier", "value", "members",
                                          "period_start", "period_end"])
        w.writeheader()
        w.writerows(out_rows)

    (OUT / "rapids_intake_meta.json").write_text(json.dumps({
        "model": "members_linear_capped",
        "median_intake": med_intake,
        "median_members": med_members,
        "cap": cap,
        "band": band,
        "mdape": round(mdape, 1),
        "p25_error": round(pct(errors, 25), 1),
        "p75_error": round(pct(errors, 75), 1),
        "rounding": rounding,
        "caveat": "standard" if band == "under_35" else "strong",
        "validation_n": len(errors),
        "rapids_display_default": rounding is not None,
    }, indent=2) + "\n", encoding="utf-8")

    print(f"\nTier counts across {len(all_lus)} locals: {tiers}")
    print("\nFiles touched:")
    for n in ("rapids_intake_validation.csv", "rapids_intake_estimate_by_lu.csv",
              "rapids_intake_meta.json"):
        print(f"  out/{n}")


if __name__ == "__main__":
    main()
