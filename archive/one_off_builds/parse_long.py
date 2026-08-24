import csv
import json
import os

RAW_DIR = "raw"
LOCALS_DIR = os.path.join(RAW_DIR, "locals")

with open(os.path.join(RAW_DIR, "list_locals.json"), encoding="utf-8") as f:
    locals_index = {r["ID"]: r["LU"] for r in json.load(f)}

rows = []
mismatches = []

for local_id, lu in locals_index.items():
    path = os.path.join(LOCALS_DIR, f"{local_id}.json")
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8") as f:
        try:
            records = json.load(f)
        except json.JSONDecodeError:
            mismatches.append({"ID": local_id, "LU": lu, "reason": "invalid JSON"})
            continue

    for rec in records:
        table_name = rec.get("tableName", "")
        row_id = rec.get("idFieldValue", "")
        line_raw = rec.get("Line", "")
        names = (rec.get("editFieldNames") or "").split("|")
        values = (rec.get("editFieldValues") or "").split("|")

        if len(names) != len(values):
            mismatches.append({
                "ID": local_id,
                "LU": lu,
                "reason": "pipe count mismatch",
                "editFieldNames": rec.get("editFieldNames"),
                "editFieldValues": rec.get("editFieldValues"),
                "Line": line_raw,
                "tableName": table_name,
            })
            continue

        for fname, fval in zip(names, values):
            rows.append({
                "local_union_id": local_id,
                "lu_number": lu,
                "table_name": table_name,
                "row_id": row_id,
                "field_name": fname,
                "field_value": fval,
                "line_raw": line_raw,
            })

with open(os.path.join(RAW_DIR, "long.csv"), "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "local_union_id", "lu_number", "table_name", "row_id",
        "field_name", "field_value", "line_raw",
    ])
    writer.writeheader()
    writer.writerows(rows)

with open(os.path.join(RAW_DIR, "parse_mismatches.json"), "w", encoding="utf-8") as f:
    json.dump(mismatches, f, indent=2)

print(f"long.csv rows: {len(rows)}")
print(f"parse mismatches: {len(mismatches)}")
