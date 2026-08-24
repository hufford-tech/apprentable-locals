import csv
import json
from collections import defaultdict

RAW = "raw"

with open(f"{RAW}/long.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

with open(f"{RAW}/parse_mismatches.json", encoding="utf-8") as f:
    mismatches = json.load(f)

with open(f"{RAW}/list_locals.json", encoding="utf-8") as f:
    all_locals = json.load(f)

total_locals = len(all_locals)
lu_by_id = {r["ID"]: r["LU"] for r in all_locals}

# ---- 2. distinct tableName values, record count, locals with >=1 row ----
table_rows = defaultdict(int)          # count of raw JSON records (not long.csv rows) per table
table_locals = defaultdict(set)

with open(f"{RAW}/list_locals.json", encoding="utf-8") as f:
    pass

import os
for local_id in lu_by_id:
    path = f"{RAW}/locals/{local_id}.json"
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    for rec in records:
        tn = rec.get("tableName", "")
        table_rows[tn] += 1
        table_locals[tn].add(local_id)

print("=== 2. tableName distribution ===")
for tn in sorted(table_rows):
    print(f"  {tn}: {table_rows[tn]} records, present in {len(table_locals[tn])}/{total_locals} locals")

# ---- 3. per tableName field fill rates (based on successfully parsed long.csv rows) ----
print()
print("=== 3. Field fill rate per tableName (of 764 locals) ===")
field_local_presence = defaultdict(lambda: defaultdict(set))  # table -> field -> set(local_id) with non-empty value
field_seen_tables = defaultdict(set)

for r in rows:
    tn = r["table_name"]
    fn = r["field_name"]
    field_seen_tables[tn].add(fn)
    if r["field_value"].strip() != "":
        field_local_presence[tn][fn].add(r["local_union_id"])

low_fill_flags = []
for tn in sorted(field_seen_tables):
    print(f"  [{tn}]")
    for fn in sorted(field_seen_tables[tn]):
        n = len(field_local_presence[tn][fn])
        pct = 100.0 * n / total_locals
        flag = "  <-- UNDER 50%" if pct < 50 else ""
        print(f"      {fn}: {n}/{total_locals} = {pct:.1f}%{flag}")
        if pct < 50:
            low_fill_flags.append((tn, fn, pct))

# ---- 4. repeating-group distribution ----
print()
print("=== 4. Repeating-group distribution (Addresses, Phones, Emails, Members) ===")

# Build row_id sets straight from the raw per-local JSON, since Members rows
# are almost entirely excluded from long.csv due to the pipe-count mismatch.
raw_table_rowids = defaultdict(lambda: defaultdict(set))  # table -> local_id -> set(row_id)
for local_id in lu_by_id:
    path = f"{RAW}/locals/{local_id}.json"
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    for rec in records:
        raw_table_rowids[rec.get("tableName", "")][local_id].add(rec.get("idFieldValue", ""))

for tn in ["Addresses", "Phones", "Emails", "Members"]:
    local_rowids = raw_table_rowids[tn]
    dist = defaultdict(list)  # count -> [local_ids]
    for local_id, rids in local_rowids.items():
        n = len(rids)
        bucket = n if n <= 2 else "3+"
        dist[bucket].append(local_id)
    print(f"  [{tn}]")
    for bucket in sorted(dist, key=lambda x: (isinstance(x, str), x)):
        ids = dist[bucket]
        print(f"      {bucket} row(s): {len(ids)} locals")
    max_n = max((len(v) for v in local_rowids.values()), default=0)
    max_locals = [lid for lid, rids in local_rowids.items() if len(rids) == max_n]
    if max_locals:
        example = max_locals[0]
        print(f"      max = {max_n} rows, e.g. local_union_id={example} (LU {lu_by_id.get(example)})")

# ---- 5. TradeClasses frequency table ----
print()
print("=== 5. TradeClasses frequency table (locals carrying each code) ===")
tc_local_codes = defaultdict(set)  # code -> set(local_id)
for r in rows:
    if r["table_name"] == "TradeClasses" and r["field_name"] == "TradeClassDesc":
        codes = [c.strip() for c in r["field_value"].split(",") if c.strip()]
        for c in codes:
            tc_local_codes[c].add(r["local_union_id"])

for code in sorted(tc_local_codes, key=lambda c: -len(tc_local_codes[c])):
    n = len(tc_local_codes[code])
    print(f"  {code}: {n} locals ({100.0*n/total_locals:.1f}%)")

# ---- 6. parse mismatches summary ----
print()
print("=== 6. Parse mismatches ===")
print(f"  total mismatches logged: {len(mismatches)}")
by_table = defaultdict(int)
for m in mismatches:
    by_table[m.get("tableName", "?")] += 1
for tn, n in sorted(by_table.items(), key=lambda x: -x[1]):
    print(f"    {tn}: {n}")

print()
print("=== low fill-rate flags (<50%) ===")
for tn, fn, pct in low_fill_flags:
    print(f"  {tn}.{fn}: {pct:.1f}%")
