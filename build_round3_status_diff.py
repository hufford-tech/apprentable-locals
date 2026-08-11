"""
out/round3_status_diff.csv -- every local whose computed_status,
status_confidence, or intake_pattern changed between the round-2 committed
state (compute_status.py @ 6ff892c) and now. Attributes which task caused it
by also computing an intermediate state (compute_status.py @ ac9deb6, i.e.
after task 1's classify_intake fix but before task 3's recurring-window
resolution).
"""
import csv
import datetime
import importlib.util
import json
import os

from compute_status import compute_status as compute_status_now
from build_verify_worklist import pick_decisive_evidence

OUT_PATH = "out/round3_status_diff.csv"
SCRATCH_DIR = r"C:\Users\andre\AppData\Local\Temp\claude\c--Users-andre-ibew-prep\f6947bee-ed05-4a4f-89d7-46915f459355\scratchpad"


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    before_mod = _load_module(os.path.join(SCRATCH_DIR, "compute_status_before.py"), "compute_status_r2")
    after_task1_mod = _load_module(os.path.join(SCRATCH_DIR, "compute_status_after_task1.py"), "compute_status_r3t1")

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    today = datetime.date.today()

    def pop_val(lu):
        try:
            return float(pop_rows.get(lu, {}).get("population_current_served_inside", "") or 0)
        except (ValueError, TypeError):
            return 0.0

    out_rows = []
    for r in rows:
        lu = r["lu_number"]
        windows = json.loads(r["windows_json"]) if r.get("windows_json") else []
        statements = json.loads(r["status_statements_json"]) if r.get("status_statements_json") else []
        record = {"windows": windows, "status_statements": statements, "page_last_updated": r.get("page_last_updated") or None}

        before = before_mod.compute_status(record)
        after_t1 = after_task1_mod.compute_status(record)
        after_now = compute_status_now(record)

        b_status, b_conf, b_pattern = before["computed_status"], before["status_confidence"], before.get("intake_pattern", "")
        a_status, a_conf, a_pattern = after_now["computed_status"], after_now["status_confidence"], after_now.get("intake_pattern", "")

        if b_status == a_status and b_conf == a_conf and b_pattern == a_pattern:
            continue

        t1_changed = (before["computed_status"], before["status_confidence"], before.get("intake_pattern", "")) != \
                     (after_t1["computed_status"], after_t1["status_confidence"], after_t1.get("intake_pattern", ""))
        t3_changed = (after_t1["computed_status"], after_t1["status_confidence"]) != \
                     (after_now["computed_status"], after_now["status_confidence"])

        if t1_changed and t3_changed:
            which_task = "task1+task3"
        elif t1_changed:
            which_task = "task1"
        elif t3_changed:
            which_task = "task3"
        else:
            which_task = "unknown"  # shouldn't happen, but don't silently misattribute

        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})

        quote, source_url = pick_decisive_evidence(a_status, today, windows, statements)

        out_rows.append({
            "local_union_id": local_union_id,
            "lu_number": lu,
            "charter_city": p.get("charter_city", ""),
            "population_current_served_inside": p.get("population_current_served_inside", ""),
            "status_before": b_status,
            "status_after": a_status,
            "confidence_before": b_conf,
            "confidence_after": a_conf,
            "intake_pattern_before": b_pattern,
            "intake_pattern_after": a_pattern,
            "which_task_caused_it": which_task,
            "evidence_quote": quote[:300],
            "source_url": source_url,
            "_pop_sort": pop_val(lu),
        })

    out_rows.sort(key=lambda r: r["_pop_sort"], reverse=True)
    for r in out_rows:
        del r["_pop_sort"]

    fieldnames = [
        "local_union_id", "lu_number", "charter_city", "population_current_served_inside",
        "status_before", "status_after", "confidence_before", "confidence_after",
        "intake_pattern_before", "intake_pattern_after", "which_task_caused_it",
        "evidence_quote", "source_url",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {OUT_PATH}: {len(out_rows)} locals changed")
    from collections import Counter
    print("by which_task_caused_it:", dict(Counter(r["which_task_caused_it"] for r in out_rows)))


if __name__ == "__main__":
    main()
