"""
Audit EVERY status_statement across all 242 locals, all statement_type
values -- not just the rolling defect fixed in compute_status.py. Flags are
heuristic keyword checks, same spirit/caveats as classify_intake(): reviewable,
tune the word lists, not the logic.
"""
import csv
import json
import re
from collections import Counter

from compute_status import classify_intake

OUT_PATH = "out/statement_label_audit.csv"

CLOSURE_WORDS = [
    "closed", "not accepting", "not currently", "suspended", "list is full",
    "no longer accepting",
]

ELIGIBILITY_WORDS = [
    "must be", "high school diploma", "driver's license", "drivers license",
    "transcript", "dd-214", "18 years", "years of age", "citizen",
    "aptitude test", "math credit", "algebra", "ged",
]

# words that indicate the text is actually making a status claim, as opposed
# to being pure eligibility/requirements copy
STATUS_INDICATOR_WORDS = [
    "accept", "apply", "application", "open", "closed", "deadline", "enroll",
    "recruit", "intake",
]

# words that indicate the text is describing HOW to apply (method/mechanics)
# rather than WHETHER applications are currently being taken
METHOD_WORDS = [
    "online", "portal", "website", "create an account", "click the link",
    "in person at", "call the office", "mail your application", "email your",
]

# words indicating an active "we are open/accepting right now" claim
OPEN_STATUS_WORDS = [
    "open", "accepting", "now accepting", "currently accepting", "we accept",
]

_MONTH_NAME_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b"
)
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def has_date_in_text(low):
    return bool(_MONTH_NAME_RE.search(low) or _NUMERIC_DATE_RE.search(low) or _YEAR_RE.search(low))


def is_eligibility_only(low):
    has_elig = any(k in low for k in ELIGIBILITY_WORDS)
    has_status = any(k in low for k in STATUS_INDICATOR_WORDS)
    return has_elig and not has_status


def detect_disagreement(statement_type, text, stated_effective_date):
    low = (text or "").lower()

    if is_eligibility_only(low):
        return True, "eligibility_not_status"

    if statement_type == "rolling" and classify_intake(text) == "none":
        return True, "rolling_no_temporal_language"

    if statement_type == "closed" and not any(k in low for k in CLOSURE_WORDS):
        return True, "closed_no_closure_language"

    if statement_type == "reopening":
        if not stated_effective_date and not has_date_in_text(low):
            return True, "reopening_no_date_anywhere"

    if statement_type == "open":
        has_open_status = any(k in low for k in OPEN_STATUS_WORDS)
        has_method = any(k in low for k in METHOD_WORDS)
        if not has_open_status and has_method:
            return True, "open_describes_method_not_status"

    return False, ""


def main():
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    crosswalk = {lu: r["local_union_id"] for lu, r in pop_rows.items()}

    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    type_counts = Counter()
    reason_counts = Counter()

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
            stype = s.get("statement_type", "")
            text = s.get("verbatim_text", "")
            sed = s.get("stated_effective_date")
            type_counts[stype] += 1

            flag, reason = detect_disagreement(stype, text, sed)
            if flag:
                reason_counts[reason] += 1

            out_rows.append({
                "local_union_id": local_union_id,
                "lu_number": lu,
                "statement_type": stype,
                "verbatim_text": text[:300],
                "stated_effective_date": sed or "",
                "source_url": s.get("source_url", ""),
                "classify_intake_result": classify_intake(text),
                "disagreement_flag": str(flag),
                "disagreement_reason": reason,
                "_pop_sort": pop_val,
                "_disagree_sort": 0 if flag else 1,
            })

    out_rows.sort(key=lambda r: (r["_disagree_sort"], -r["_pop_sort"]))
    for r in out_rows:
        del r["_pop_sort"]
        del r["_disagree_sort"]

    fieldnames = [
        "local_union_id", "lu_number", "statement_type", "verbatim_text",
        "stated_effective_date", "source_url", "classify_intake_result",
        "disagreement_flag", "disagreement_reason",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    total_flagged = sum(1 for r in out_rows if r["disagreement_flag"] == "True")
    print(f"Wrote {OUT_PATH}: {len(out_rows)} statements, {total_flagged} flagged")
    print(f"\nCount by statement_type: {dict(type_counts)}")
    print(f"\nCount by disagreement_reason: {dict(reason_counts)}")


if __name__ == "__main__":
    main()
