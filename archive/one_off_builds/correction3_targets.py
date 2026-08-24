import csv

CANADIAN_PROVINCES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}

with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
    locals_rows = {r["lu_number"]: r for r in csv.DictReader(f)}

with open("out/trade_classes.csv", encoding="utf-8") as f:
    tc_rows = list(csv.DictReader(f))

tc_by_lu = {}
for r in tc_rows:
    tc_by_lu.setdefault(r["lu_number"], []).append(r["trade_class_code"])

with open("out/emails.csv", encoding="utf-8") as f:
    email_rows = list(csv.DictReader(f))

has_email_by_lu = set()
for r in email_rows:
    if r["Email"].strip():
        has_email_by_lu.add(r["lu_number"])

i_lus = [lu for lu, classes in tc_by_lu.items() if "i" in classes]

us_i_lus = [
    lu for lu in i_lus
    if locals_rows.get(lu, {}).get("charter_state", "").strip().upper() not in CANADIAN_PROVINCES
]

print(f"Class 'i' locals: {len(i_lus)}")
print(f"Of those, US (non-Canadian charter state): {len(us_i_lus)}")

with_website = [lu for lu in us_i_lus if locals_rows.get(lu, {}).get("website", "").strip()]
without_website = [lu for lu in us_i_lus if not locals_rows.get(lu, {}).get("website", "").strip()]

print(f"  with website: {len(with_website)}  -> out/scrape_targets.csv")
print(f"  without website: {len(without_website)}  -> out/no_website_targets.csv")


def members_sort_key(lu):
    v = locals_rows.get(lu, {}).get("olms_members", "").strip()
    try:
        return (0, -float(v))
    except ValueError:
        return (1, 0)


def write_targets(path, lus):
    rows = []
    for lu in lus:
        r = locals_rows[lu]
        rows.append({
            "local_union_id": r["local_union_id"],
            "lu_number": lu,
            "website": r["website"],
            "olms_members": r["olms_members"],
            "charter_city": r["charter_city"],
            "charter_state": r["charter_state"],
            "trade_classes": ",".join(sorted(tc_by_lu.get(lu, []))),
            "has_email": "yes" if lu in has_email_by_lu else "no",
            "meets": r["meets"],
        })
    rows.sort(key=lambda row: members_sort_key(row["lu_number"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "local_union_id", "lu_number", "website", "olms_members",
            "charter_city", "charter_state", "trade_classes", "has_email", "meets",
        ])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


n1 = write_targets("out/scrape_targets.csv", with_website)
n2 = write_targets("out/no_website_targets.csv", without_website)
print(f"Wrote out/scrape_targets.csv: {n1} rows")
print(f"Wrote out/no_website_targets.csv: {n2} rows")
