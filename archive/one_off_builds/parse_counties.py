import csv
import json
import os

RAW = "raw"
OUT = "out"

with open(f"{RAW}/list_locals.json", encoding="utf-8") as f:
    lu_by_id = {r["LU"]: r["ID"] for r in json.load(f)}

rows = []
for lu, local_id in lu_by_id.items():
    path = f"{RAW}/counties/{lu}.json"
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8") as f:
        try:
            records = json.load(f)
        except json.JSONDecodeError:
            continue
    for rec in records:
        rows.append({
            "lu_number": lu,
            "local_union_id": local_id,
            "state_province": rec.get("StateProvince", ""),
            "county_name": rec.get("CountyName", ""),
            "district": rec.get("District", ""),
            "population": rec.get("Population", ""),
            "land_area": rec.get("LandArea", ""),
            "percentage": rec.get("Percentage", ""),
            "jurisdiction_type": rec.get("jurisdiction", ""),
            "raw_line": json.dumps(rec, ensure_ascii=False),
        })

with open(f"{OUT}/jurisdictions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=[
        "lu_number", "local_union_id", "state_province", "county_name", "district",
        "population", "land_area", "percentage", "jurisdiction_type", "raw_line",
    ])
    w.writeheader()
    w.writerows(rows)

print(f"Wrote {OUT}/jurisdictions.csv: {len(rows)} rows from {len(lu_by_id)} locals")
