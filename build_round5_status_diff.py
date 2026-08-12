"""out/round5_status_diff.csv -- every local whose computed_status,
status_confidence, next_open_date, or next_close_date changed between the
committed pre-round-5 compute_status.py (git blob fde1989, the last commit to
touch the file before this round) and the current one.

Same shape as build_round4_status_diff.py, with three round-5 columns added:
embedded_date_conflict, rejected_statement_count, reject_reasons (the
admit_statement reject_reason values seen across the record's statements,
'|'-joined).
"""
import csv
import datetime
import importlib.util
import json
import os
from collections import Counter

from compute_status import compute_status as compute_status_now
from statement_evidence import admit_statement

OUT_PATH = "out/round5_status_diff.csv"
BEFORE_BLOB = "fde1989:compute_status.py"


def _load_before_module():
    src = os.popen(f'git show {BEFORE_BLOB}').read()
    if not src.strip():
        raise SystemExit(f"git show {BEFORE_BLOB} returned nothing -- wrong blob?")
    tmp_path = os.path.join(os.environ.get("TEMP", "."), "compute_status_before_round5.py")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("compute_status_r4", tmp_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pick_evidence(statements, windows):
    for want in ("open", "closed", "reopening", "unknown", "rolling"):
        for s in statements:
            if s.get("statement_type") == want and s.get("verbatim_text"):
                return s["verbatim_text"], s.get("source_url", "")
    for w in windows:
        if w.get("evidence_quote"):
            return w["evidence_quote"], w.get("source_url", "")
    return "", ""


def _attribute_tasks(record, today, before, after, statements):
    tags = []

    has_open_stmt = any(s.get("statement_type") == "open" for s in statements)
    any_rejected = any(not admit_statement(s, today)["admissible"] for s in statements)
    if has_open_stmt and any_rejected and after["computed_status"] != "open" and before["computed_status"] == "open":
        tags.append("task1_open_statement_rejected")

    if after.get("embedded_date_conflict"):
        tags.append("task2_embedded_date_conflict")

    for s in statements:
        if s.get("statement_type") == "open":
            ev = admit_statement(s, today)
            for b in ev["embedded_bounds"]:
                if b["role"] == "start":
                    tags.append("task2_future_start")
                elif b["role"] == "bound" and b["date"] < today:
                    tags.append("task2_past_bound")

    if before.get("next_close_date") != after.get("next_close_date") and after.get("next_open_date") == before.get("next_open_date"):
        tags.append("task3_lu466_family_next_open_vs_close")

    if before.get("status_confidence") != after.get("status_confidence") and before.get("computed_status") == after.get("computed_status") == "open":
        tags.append("task3_bounded_window_confidence")

    if not tags:
        tags.append("task1_admissibility_or_unattributed")
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return "+".join(out)


def main():
    before_mod = _load_before_module()

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        csv.field_size_limit(10_000_000)
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
        record = {"windows": windows, "status_statements": statements,
                  "page_last_updated": r.get("page_last_updated") or None}

        before = before_mod.compute_status(record, today=today)
        after = compute_status_now(record, today=today)

        b_status, b_conf = before["computed_status"], before["status_confidence"]
        a_status, a_conf = after["computed_status"], after["status_confidence"]
        b_next_open = before.get("next_open_date", "")
        a_next_open = after.get("next_open_date", "")
        b_next_close = before.get("next_close_date", "")
        a_next_close = after.get("next_close_date", "")

        if (b_status, b_conf, b_next_open, b_next_close) == (a_status, a_conf, a_next_open, a_next_close):
            continue

        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})

        quote, source_url = _pick_evidence(statements, windows)
        which_task = _attribute_tasks(record, today, before, after, statements)

        reject_reasons = sorted({
            admit_statement(s, today)["reject_reason"]
            for s in statements
            if not admit_statement(s, today)["admissible"]
        })

        out_rows.append({
            "local_union_id": local_union_id,
            "lu_number": lu,
            "charter_city": p.get("charter_city", ""),
            "population_current_served_inside": p.get("population_current_served_inside", ""),
            "status_before": b_status,
            "status_after": a_status,
            "confidence_before": b_conf,
            "confidence_after": a_conf,
            "next_open_before": b_next_open,
            "next_open_after": a_next_open,
            "next_close_date_before": b_next_close,
            "next_close_date_after": a_next_close,
            "embedded_date_conflict": after.get("embedded_date_conflict", False),
            "rejected_statement_count": after.get("rejected_statement_count", 0),
            "reject_reasons": "|".join(reject_reasons),
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
        "next_open_before", "next_open_after", "next_close_date_before", "next_close_date_after",
        "embedded_date_conflict", "rejected_statement_count", "reject_reasons",
        "which_task_caused_it", "evidence_quote", "source_url",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {OUT_PATH}: {len(out_rows)} locals changed")
    print("status_before -> status_after pairs:",
          dict(Counter(f'{r["status_before"]}->{r["status_after"]}' for r in out_rows)))
    print("locals with embedded_date_conflict:", sum(1 for r in out_rows if r["embedded_date_conflict"]))


if __name__ == "__main__":
    main()
