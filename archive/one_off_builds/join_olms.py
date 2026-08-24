import csv

OUT = "out"

with open(f"{OUT}/locals.csv", encoding="utf-8") as f:
    locals_rows = list(csv.DictReader(f))

with open("olms/ibew_locals_olms_fy2025.csv", encoding="utf-8") as f:
    olms_rows = list(csv.DictReader(f))


def norm_lu(x):
    # OLMS local_number is like "1245.0"; directory LU is like "1245"
    x = (x or "").strip()
    if x.endswith(".0"):
        x = x[:-2]
    return x


locals_by_lu = {}
for r in locals_rows:
    lu = (r["lu_number"] or "").strip()
    locals_by_lu.setdefault(lu, []).append(r)

olms_by_lu = {}
skipped_blank_lu = 0
for r in olms_rows:
    lu = norm_lu(r["local_number"])
    if not lu:
        skipped_blank_lu += 1
        continue
    olms_by_lu.setdefault(lu, []).append(r)

matched_lu = set(locals_by_lu) & set(olms_by_lu)
unmatched_directory = sorted(set(locals_by_lu) - set(olms_by_lu), key=lambda x: int(x))
unmatched_olms = sorted(set(olms_by_lu) - set(locals_by_lu), key=lambda x: int(x))

print(f"Directory locals: {len(locals_rows)} (distinct LU: {len(locals_by_lu)})")
print(f"OLMS rows: {len(olms_rows)} (blank/no local_number: {skipped_blank_lu}, distinct LU: {len(olms_by_lu)})")
print(f"Matched LU: {len(matched_lu)}")
print(f"Match rate vs directory: {100.0*len(matched_lu)/len(locals_by_lu):.1f}%")
print(f"Match rate vs OLMS: {100.0*len(matched_lu)/len(olms_by_lu):.1f}%")
print()
print(f"Directory locals with NO OLMS match ({len(unmatched_directory)}):")
print(unmatched_directory)
print()
print(f"OLMS rows with NO directory match ({len(unmatched_olms)}):")
print(unmatched_olms)

# Build joined output
fieldnames = list(locals_rows[0].keys()) + [
    "olms_members", "olms_ttl_receipts", "olms_ttl_assets", "olms_dues_per_member",
    "olms_city", "olms_state", "olms_form_type",
]
joined = []
for lu, recs in locals_by_lu.items():
    for r in recs:
        row = dict(r)
        if lu in olms_by_lu:
            o = olms_by_lu[lu][0]
            row["olms_members"] = o["MEMBERS"]
            row["olms_ttl_receipts"] = o["TTL_RECEIPTS"]
            row["olms_ttl_assets"] = o["TTL_ASSETS"]
            row["olms_dues_per_member"] = o["dues_per_member"]
            row["olms_city"] = o["CITY"]
            row["olms_state"] = o["STATE"]
            row["olms_form_type"] = o["FORM_TYPE"]
        else:
            for k in ["olms_members", "olms_ttl_receipts", "olms_ttl_assets",
                      "olms_dues_per_member", "olms_city", "olms_state", "olms_form_type"]:
                row[k] = ""
        joined.append(row)

with open(f"{OUT}/locals_joined_olms.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(joined)

print()
print(f"Wrote {OUT}/locals_joined_olms.csv with {len(joined)} rows")
