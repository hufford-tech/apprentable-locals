import json
import os
import re

RAW = "raw"

with open(f"{RAW}/list_locals.json", encoding="utf-8") as f:
    lu_by_id = {r["ID"]: r["LU"] for r in json.load(f)}

# Role-flag -> canonical title fragments used in the BBCode Line
ROLE_TITLE = {
    "BM": "B.M.",
    "PRES": "Pres.",
    "FS": "F.S.",
    "RS": "R.S.",
}

repaired_rows = []          # local_union_id, lu_number, table_name, row_id, field_name, field_value, line_raw
bad_json = []                # rows where bs did not parse as JSON
pos_has_brace = []           # rows where recovered pos still contains "{"
title_mismatches = []        # rows where Line's displayed title doesn't match pos or role flags

FIELD_NAMES = ["fname", "mi", "lname", "suffix", "pos", "bs"]

for local_id, lu in lu_by_id.items():
    path = f"{RAW}/locals/{local_id}.json"
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    for rec in records:
        if rec.get("tableName") != "Members":
            continue
        names = (rec.get("editFieldNames") or "").split("|")
        values = (rec.get("editFieldValues") or "").split("|")
        line_raw = rec.get("Line", "")
        row_id = rec.get("idFieldValue", "")

        if names != FIELD_NAMES:
            # Unexpected shape entirely; don't guess.
            bad_json.append({
                "ID": local_id, "LU": lu, "row_id": row_id,
                "reason": "unexpected field name list", "editFieldNames": rec.get("editFieldNames"),
            })
            continue

        if len(values) != 5:
            bad_json.append({
                "ID": local_id, "LU": lu, "row_id": row_id,
                "reason": f"expected 5 pipe-split values, got {len(values)}",
                "editFieldValues": rec.get("editFieldValues"),
            })
            continue

        fname, mi, lname, suffix, combined = values
        brace_idx = combined.find("{")
        if brace_idx == -1:
            bad_json.append({
                "ID": local_id, "LU": lu, "row_id": row_id,
                "reason": "no '{' found in 5th value", "combined": combined,
            })
            continue

        pos = combined[:brace_idx]
        bs_raw = combined[brace_idx:]

        try:
            bs = json.loads(bs_raw)
        except json.JSONDecodeError as e:
            bad_json.append({
                "ID": local_id, "LU": lu, "row_id": row_id,
                "reason": f"bs JSON parse error: {e}", "bs_raw": bs_raw,
            })
            continue

        if "{" in pos:
            pos_has_brace.append({
                "ID": local_id, "LU": lu, "row_id": row_id, "pos": pos,
            })

        # Validate title in Line matches pos or role flags in bs
        active_roles = [r for r in ROLE_TITLE if str(bs.get(r, "")).lower() == "yes"]
        expected_titles = set()
        if pos.strip():
            expected_titles.add(pos.strip().rstrip(".").lower())
        for r in active_roles:
            expected_titles.add(ROLE_TITLE[r].rstrip(".").lower())

        line_lower = line_raw.lower()
        matched = any(t and t in line_lower for t in expected_titles)
        if not matched:
            title_mismatches.append({
                "ID": local_id, "LU": lu, "row_id": row_id,
                "pos": pos, "active_roles": active_roles, "Line": line_raw,
            })

        repaired_fields = {
            "fname": fname, "mi": mi, "lname": lname, "suffix": suffix,
            "pos": pos,
        }
        for fn, fv in repaired_fields.items():
            repaired_rows.append({
                "local_union_id": local_id, "lu_number": lu, "table_name": "Members",
                "row_id": row_id, "field_name": fn, "field_value": fv, "line_raw": line_raw,
            })
        for k, v in bs.items():
            repaired_rows.append({
                "local_union_id": local_id, "lu_number": lu, "table_name": "Members",
                "row_id": row_id, "field_name": f"bs.{k}", "field_value": v, "line_raw": line_raw,
            })

print(f"Total Members rows processed successfully: {len(repaired_rows) // 0 if False else 'n/a'}")
print(f"Rows with valid repair: {sum(1 for r in repaired_rows if r['field_name']=='fname')}")
print(f"bs JSON parse failures / bad shape: {len(bad_json)}")
print(f"pos containing '{{': {len(pos_has_brace)}")
print(f"title mismatches: {len(title_mismatches)}")

with open(f"{RAW}/members_repair_bad_json.json", "w", encoding="utf-8") as f:
    json.dump(bad_json, f, indent=2)
with open(f"{RAW}/members_repair_pos_brace.json", "w", encoding="utf-8") as f:
    json.dump(pos_has_brace, f, indent=2)
with open(f"{RAW}/members_repair_title_mismatches.json", "w", encoding="utf-8") as f:
    json.dump(title_mismatches, f, indent=2)
with open(f"{RAW}/members_repaired_rows.json", "w", encoding="utf-8") as f:
    json.dump(repaired_rows, f, indent=2)
