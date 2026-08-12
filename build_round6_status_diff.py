"""out/round6_status_diff.csv -- every local whose computed_status,
status_confidence, or next_open_date changed between the committed
pre-round-6 compute_status.py/statement_evidence.py (git blob a584a1c, the
commit HEAD was on when round 6 started) and the current ones.

Both compute_status.py and statement_evidence.py changed this round (unlike
round 5, which only touched compute_status.py), and the two modules import
each other by name at exec/call time. To diff against the true "before"
state without a git checkout, the before-versions are executed into
sys.modules under the SAME names ('compute_status', 'statement_evidence')
so their mutual imports resolve against each other, not against the current
files on disk -- then the originals are restored so the rest of this script
(and any code imported after) sees the current, "after" versions.
"""
import csv
import datetime
import json
import sys
import types
from collections import Counter

from compute_status import compute_status as compute_status_now
from statement_evidence import admit_statement, statement_labels

OUT_PATH = "out/round6_status_diff.csv"
BEFORE_COMMIT = "a584a1c"


def _git_show(commit, path):
    import subprocess
    out = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, check=True)
    return out.stdout


def _load_before_pair(commit):
    cs_src = _git_show(commit, "compute_status.py")
    se_src = _git_show(commit, "statement_evidence.py")

    cs_mod = types.ModuleType("compute_status")
    se_mod = types.ModuleType("statement_evidence")

    saved = {name: sys.modules.get(name) for name in ("compute_status", "statement_evidence")}
    sys.modules["compute_status"] = cs_mod
    sys.modules["statement_evidence"] = se_mod
    try:
        exec(compile(cs_src, "compute_status@before.py", "exec"), cs_mod.__dict__)
        exec(compile(se_src, "statement_evidence@before.py", "exec"), se_mod.__dict__)
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
    return cs_mod, se_mod


def _pick_evidence(statements, windows):
    for want in ("open", "closed", "reopening", "unknown", "rolling"):
        for s in statements:
            if s.get("statement_type") == want and s.get("verbatim_text"):
                return s["verbatim_text"], s.get("source_url", "")
    for w in windows:
        if w.get("evidence_quote"):
            return w["evidence_quote"], w.get("source_url", "")
    return "", ""


def _attribute_task(record, today, before, after, statements, windows):
    b_status, a_status = before["computed_status"], after["computed_status"]

    dated_windows = [
        w for w in windows
        if w.get("precision") == "absolute" and w.get("open_date")
    ]
    all_closed = bool(dated_windows) and all(
        w.get("close_date") and w["close_date"] < today.isoformat() for w in dated_windows
    )
    has_open_stmt = any(s.get("statement_type") == "open" for s in statements)
    if b_status == "open" and a_status == "expired_data" and has_open_stmt and all_closed:
        return "task1_dated_window_beats_prose"

    has_journeyman_ce = any(
        "continuing education" in (s.get("verbatim_text", "") or "").lower()
        for s in statements
    )
    if has_journeyman_ce and admit_statement(
        next(s for s in statements if "continuing education" in (s.get("verbatim_text", "") or "").lower()),
        today,
    )["reject_reason"] == "program_mismatch":
        return "task2_program_mismatch_gate"

    if b_status == "unknown" and a_status == "closed":
        return "task3_lu130_promotion"

    dup_texts = Counter(
        (s.get("verbatim_text", "") or "").strip().lower() for s in statements
    )
    if any(c > 1 for c in dup_texts.values()):
        return "task4_dedup"

    return "task2_closed_reopening_gate"


def main():
    cs_before, se_before = _load_before_pair(BEFORE_COMMIT)

    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        csv.field_size_limit(10_000_000)
        rows = list(csv.DictReader(f))

    today = datetime.date(2026, 8, 10)

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

        before = cs_before.compute_status(record, today=today)
        after = compute_status_now(record, today=today)

        b_status, b_conf = before["computed_status"], before["status_confidence"]
        a_status, a_conf = after["computed_status"], after["status_confidence"]
        b_next_open = before.get("next_open_date", "")
        a_next_open = after.get("next_open_date", "")

        if (b_status, b_conf, b_next_open) == (a_status, a_conf, a_next_open):
            continue

        local_union_id = crosswalk.get(lu)
        if local_union_id is None:
            raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
        p = pop_rows.get(lu, {})

        quote, source_url = _pick_evidence(statements, windows)
        which_task = _attribute_task(record, today, before, after, statements, windows)

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
        "next_open_before", "next_open_after", "which_task_caused_it", "evidence_quote", "source_url",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {OUT_PATH}: {len(out_rows)} locals changed")
    print("status_before -> status_after pairs:",
          dict(Counter(f'{r["status_before"]}->{r["status_after"]}' for r in out_rows)))
    print("which_task_caused_it counts:", dict(Counter(r["which_task_caused_it"] for r in out_rows)))


if __name__ == "__main__":
    main()
