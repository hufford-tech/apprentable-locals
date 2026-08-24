# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/build_statement_admissibility_audit.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

"""
Round 5, task 4: out/statement_admissibility_audit.csv -- one row per
status_statement across all 242 locals, run through statement_evidence's
admit_statement() gate.

Supersedes out/statement_label_audit.csv (round 2). That file is left in
place -- it answers a narrower question (does a statement's own text agree
with its own statement_type label, via a handful of type-specific keyword
checks) and nothing here deletes it. This file answers the broader question
round 5 exists to raise: across the WHOLE corpus, how often does the
LLM-assigned statement_type label simply disagree with what a demote-only,
independent text read (`asserts`) would conclude? That confusion matrix is
the actual deliverable -- it is the number that decides whether paying for
re-extraction is worth it, not any single local's fix.
"""
import csv
import datetime
import json
from collections import Counter

from statement_evidence import admit_statement

OUT_PATH = "out/statement_admissibility_audit.csv"
TODAY = datetime.date.today()


def main():
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        csv.field_size_limit(10_000_000)
        rows = list(csv.DictReader(f))

    out_rows = []
    reject_reason_counts = Counter()
    label_disagree_counts = Counter()
    confusion = Counter()  # (statement_type, asserts) -> count

    for r in rows:
        lu = r["lu_number"]
        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})
        try:
            pop_val = float(p.get("population_current_served_inside", "") or 0)
        except (ValueError, TypeError):
            pop_val = 0.0

        statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
        for s in statements:
            stype = s.get("statement_type", "") or ""
            text = s.get("verbatim_text", "") or ""
            ev = admit_statement(s, TODAY)

            label_disagrees = stype != ev["asserts"]
            confusion[(stype, ev["asserts"])] += 1
            if label_disagrees:
                label_disagree_counts[f"{stype}->{ev['asserts']}"] += 1
            if not ev["admissible"]:
                reject_reason_counts[ev["reject_reason"]] += 1

            out_rows.append({
                "local_union_id": local_union_id,
                "lu_number": lu,
                "charter_city": p.get("charter_city", ""),
                "population": p.get("population_current_served_inside", ""),
                "statement_type": stype,
                "asserts": ev["asserts"],
                "label_disagrees": str(label_disagrees),
                "admissible": str(ev["admissible"]),
                "reject_reason": ev["reject_reason"],
                "tense": ev["tense"],
                "scope": ev["scope"],
                "program": ev["program"],
                "embedded_dates": "|".join(d.isoformat() for d in ev["embedded_dates"]),
                "embedded_date_conflict": str(ev["embedded_date_conflict"]),
                "verbatim_text": text[:300],
                "source_url": s.get("source_url", ""),
                "_pop_sort": pop_val,
                "_disagree_sort": 0 if label_disagrees else 1,
            })

    out_rows.sort(key=lambda row: (row["_disagree_sort"], -row["_pop_sort"]))
    for row in out_rows:
        del row["_pop_sort"]
        del row["_disagree_sort"]

    fieldnames = [
        "local_union_id", "lu_number", "charter_city", "population",
        "statement_type", "asserts", "label_disagrees", "admissible",
        "reject_reason", "tense", "scope", "program", "embedded_dates",
        "embedded_date_conflict", "verbatim_text", "source_url",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    total = len(out_rows)
    total_disagree = sum(label_disagree_counts.values())
    total_rejected = sum(reject_reason_counts.values())
    print(f"Wrote {OUT_PATH}: {total} statements")
    print(f"\nlabel_disagrees: {total_disagree} of {total} ({100*total_disagree/total:.1f}%)")
    print(f"  by transition: {dict(label_disagree_counts.most_common())}")
    print(f"\nrejected: {total_rejected} of {total} ({100*total_rejected/total:.1f}%)")
    print(f"  by reject_reason: {dict(reject_reason_counts.most_common())}")
    print("\nconfusion matrix (statement_type -> asserts):")
    for (stype, asserts), count in sorted(confusion.items(), key=lambda kv: -kv[1]):
        print(f"  {stype or '(blank)':12} -> {asserts:10} : {count}")


if __name__ == "__main__":
    main()
