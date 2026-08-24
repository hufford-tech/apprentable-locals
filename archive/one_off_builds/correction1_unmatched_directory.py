import csv

CANADIAN_PROVINCES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}

with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
    all_rows = list(csv.DictReader(f))

with open("out/trade_classes.csv", encoding="utf-8") as f:
    tc_rows = list(csv.DictReader(f))

tc_by_lu = {}
for r in tc_rows:
    tc_by_lu.setdefault(r["lu_number"], []).append(r["trade_class_code"])


def norm_lu(x):
    x = (x or "").strip()
    if x.endswith(".0"):
        x = x[:-2]
    return x


with open("olms/ibew_locals_olms_fy2025.csv", encoding="utf-8") as f:
    olms_lu_set = {norm_lu(r["local_number"]) for r in csv.DictReader(f) if norm_lu(r["local_number"])}

unmatched = [r for r in all_rows if r["lu_number"].strip() not in olms_lu_set]
print(f"Total unmatched directory locals: {len(unmatched)}")

canadian = [r for r in unmatched if r["charter_state"].strip().upper() in CANADIAN_PROVINCES]
us = [r for r in unmatched if r["charter_state"].strip().upper() not in CANADIAN_PROVINCES]

print(f"Canadian: {len(canadian)}")
print(f"US (real gap): {len(us)}")
print()

other_states = sorted(set(r["charter_state"].strip().upper() for r in us))
print(f"Charter states among the US remainder: {other_states}")
print()

print("US unmatched locals detail:")
print(f'{"LU":6}{"City":22}{"State":6}{"Website?":9}  Trade classes')
for r in sorted(us, key=lambda x: int(x["lu_number"])):
    lu = r["lu_number"]
    classes = ",".join(tc_by_lu.get(lu, []))
    has_site = "yes" if r["website"].strip() else "no"
    print(f'{lu:6}{r["charter_city"]:22}{r["charter_state"]:6}{has_site:9}  {classes}')
