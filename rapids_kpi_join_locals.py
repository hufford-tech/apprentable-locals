"""
Join out/rapids_locals_join.csv (lu_number -> matched PS_ID) with
out/rapids_kpi_by_program.csv (PS_ID -> KPI counts) into out/rapids_kpi_by_lu.csv,
keyed by lu_number -- the join key build_frontend_data.py already uses for every
other supplementary source (wages, contact info).

Only rows with a name- or city-confirmed match (lu_number_match,
city_fuzzy_match) are included. zip_jurisdiction_match rows are held out of
the site-facing join -- that match mechanism already caught two cases of one
program's ZIP being claimed by two different, unrelated locals during the
rapids_zip_join.py build (both excluded there because they collided; a single
wrong-but-uncontested zip match wouldn't be catchable the same way), so these
30 need a human to check each program's actual city before shipping. They are
written to out/rapids_kpi_by_lu_needs_review.csv, not discarded, so they're
one file away from being added back in once reviewed. The 6 needs-review
candidates from rapids_zip_join.py and the 40 true gaps are excluded from both
outputs, not guessed at.

Owns: out/rapids_kpi_by_lu.csv, out/rapids_kpi_by_lu_needs_review.csv. Does
not touch anything else.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

REAL_MATCH_TYPES = {"lu_number_match", "city_fuzzy_match"}

# A cancelled or deregistered program registration is not the local's current
# program. Ten locals matched only to one -- Boston 103, Springfield 7,
# Worcester 96 among them, all Massachusetts, which runs its own state
# apprenticeship agency so its federal registrations went stale. They were
# reporting 0 apprentices as a DOL-reported fact, and their zeros were also
# dragging down the estimate's reference distribution.
DEAD_STATUSES = {"Cancelled", "Deregistered", "Suspended"}
HELD_BACK_MATCH_TYPES = {"zip_jurisdiction_match"}

OUT_COLUMNS = [
    "lu_number", "match_type", "ps_id", "prog_name",
    "active_apprentices", "new_apprentices", "exiters",
    "total_apprentices_served", "period_start", "period_end",
]


def _build(join, kpi, match_types):
    subset = join[join["match_type"].isin(match_types)].copy()
    subset = subset[~subset["rapids_status"].isin(DEAD_STATUSES)]
    merged = subset.merge(
        kpi, left_on="rapids_ps_id", right_on="PS_ID", how="inner",
        suffixes=("", "_kpi"),
    )
    return merged[[
        "lu_number", "match_type", "rapids_ps_id", "rapids_name",
        "active_apprentices", "new_apprentices", "exiters",
        "total_apprentices_served", "period_start", "period_end",
    ]].rename(columns={"rapids_ps_id": "ps_id", "rapids_name": "prog_name"})


def main():
    join_path = OUT / "rapids_locals_join.csv"
    kpi_path = OUT / "rapids_kpi_by_program.csv"

    join = pd.read_csv(join_path, dtype=str, low_memory=False)
    kpi = pd.read_csv(kpi_path, dtype=str, low_memory=False)

    dead = join[join["match_type"].isin(REAL_MATCH_TYPES)
                & join["rapids_status"].isin(DEAD_STATUSES)]
    dead.to_csv(OUT / "rapids_locals_dead_program_only.csv", index=False)

    out_df = _build(join, kpi, REAL_MATCH_TYPES)
    review_df = _build(join, kpi, HELD_BACK_MATCH_TYPES)

    out_path = OUT / "rapids_kpi_by_lu.csv"
    out_df.to_csv(out_path, index=False)

    review_path = OUT / "rapids_kpi_by_lu_needs_review.csv"
    review_df.to_csv(review_path, index=False)

    print(f"Excluded {len(dead)} locals whose only match is a "
          f"cancelled/deregistered/suspended program -> out/rapids_locals_dead_program_only.csv")
    print(f"Wrote {len(out_df)} locals with KPI data to {out_path}")
    print(f"By match type: {out_df['match_type'].value_counts().to_dict()}")
    print(f"Held back {len(review_df)} zip-jurisdiction-matched locals to {review_path}")


if __name__ == "__main__":
    main()
