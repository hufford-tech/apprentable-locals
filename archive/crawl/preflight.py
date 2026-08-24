import json

with open("raw_list_locals_probe.json", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total records: {len(data)}")

ids = [r["ID"] for r in data]
lus = [r["LU"] for r in data]

dup_ids = {x for x in ids if ids.count(x) > 1}
dup_lus = {x for x in lus if lus.count(x) > 1}
bad_lu = [r for r in data if not r["LU"].strip() or not r["LU"].strip().lstrip("-").isdigit()]

print(f"Duplicate ID values: {dup_ids if dup_ids else 'none'}")
print(f"Duplicate LU values: {dup_lus if dup_lus else 'none'}")
print(f"Records with empty/non-numeric LU: {len(bad_lu)}")
for r in bad_lu:
    print("  ", r)
