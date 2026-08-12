"""out/round4_status_diff.csv -- every local whose computed_status,
status_confidence, next_open_date, or next_close_date changed between the
committed pre-round-4 compute_status.py (git blob 1880f01, the last commit to
touch the file before this round) and the current one.

which_task_caused_it is a best-effort attribution, not a precise bisection:
round 4 landed as one commit (tasks 1-7 are interdependent -- see the commit
message), so there's no separate compute_status.py snapshot per task the way
round 3 had. Attribution here is inferred from observable signals in the
record + the before/after results (an 'open'-typed statement present ->
task 2, a closed statement's stated_effective_date in the future -> task 3,
etc.), and multiple tags are joined when more than one signal fires. Read the
evidence_quote and compute_status.py's comments for the real reasoning behind
any single local.
"""
import csv
import datetime
import importlib.util
import json
import os

from compute_status import compute_status as compute_status_now

OUT_PATH = "out/round4_status_diff.csv"
BEFORE_BLOB = "1880f01:compute_status.py"


def _load_before_module():
    src = os.popen(f'git show {BEFORE_BLOB}').read()
    if not src.strip():
        raise SystemExit(f"git show {BEFORE_BLOB} returned nothing -- wrong blob?")
    tmp_path = os.path.join(os.environ.get("TEMP", "."), "compute_status_before_round4.py")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("compute_status_r3", tmp_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pick_evidence(statements, windows):
    # prefer an 'open' statement (task 2's new signal), then closed, then
    # reopening, then unknown, then any window's evidence_quote.
    for want in ("open", "closed", "reopening", "unknown", "rolling"):
        for s in statements:
            if s.get("statement_type") == want and s.get("verbatim_text"):
                return s["verbatim_text"], s.get("source_url", "")
    for w in windows:
        if w.get("evidence_quote"):
            return w["evidence_quote"], w.get("source_url", "")
    return "", ""


def _attribute_tasks(record, today, before, after):
    tags = []
    statements = record["status_statements"]
    windows = record["windows"]

    has_open_stmt = any(s.get("statement_type") == "open" for s in statements)
    if has_open_stmt and after["computed_status"] == "open" and before["computed_status"] != "open":
        tags.append("task2_open_statement")

    for s in statements:
        if s.get("statement_type") == "closed":
            eff = s.get("stated_effective_date")
            if eff:
                try:
                    d = datetime.date.fromisoformat(eff)
                    if d > today:
                        tags.append("task3_future_tense_closed")
                        break
                except ValueError:
                    pass

    from compute_status import classify_closure_scope
    for s in statements:
        if s.get("statement_type") == "closed":
            scope = classify_closure_scope(s.get("verbatim_text", ""), today)
            if scope in ("future_period", "past_cohort"):
                tags.append(f"task4_{scope}")

    if after.get("corroborated_by_unknown_stmt"):
        tags.append("task5_unknown_corroboration")

    for w in windows:
        if (w.get("precision") == "absolute" and w.get("open_date") and not w.get("close_date")):
            tags.append("task6_open_ended_decay")
            break

    if before.get("days_since_evidence") is not None and before["days_since_evidence"] < 0:
        tags.append("task1_negative_days_fixed")

    if not tags:
        tags.append("task1_evidence_recency_or_unattributed")
    # de-dup, keep order
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
        a_next_close = after.get("next_close_date", "")

        if (b_status, b_conf, b_next_open) == (a_status, a_conf, a_next_open) and not a_next_close:
            continue

        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})

        quote, source_url = _pick_evidence(statements, windows)
        which_task = _attribute_tasks(record, today, before, after)

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
            "next_close_date": a_next_close,
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
        "next_open_before", "next_open_after", "next_close_date",
        "which_task_caused_it", "evidence_quote", "source_url",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {OUT_PATH}: {len(out_rows)} locals changed")
    from collections import Counter
    print("status_before -> status_after pairs:",
          dict(Counter(f'{r["status_before"]}->{r["status_after"]}' for r in out_rows)))
    print("locals with next_close_date:", sum(1 for r in out_rows if r["next_close_date"]))


if __name__ == "__main__":
    main()
