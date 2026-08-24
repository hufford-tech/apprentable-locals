import csv

UNMATCHED_LU = ['253', '289', '1040', '1087', '1224', '1391', '1424', '1501',
                '1635', '1865', '1873', '2009', '2164', '2201', '2240']


def norm_lu(x):
    x = (x or "").strip()
    if x.endswith(".0"):
        x = x[:-2]
    return x


with open("olms/ibew_locals_olms_fy2025.csv", encoding="utf-8") as f:
    olms_rows = list(csv.DictReader(f))

olms_by_lu = {norm_lu(r["local_number"]): r for r in olms_rows}

with open("olms/ibew_non_local_entities_fy2025.csv", encoding="utf-8") as f:
    non_local_rows = list(csv.DictReader(f))

non_local_by_num = {}
for r in non_local_rows:
    num = (r["DESIG_NUM"] or "").strip()
    if num.endswith(".0"):
        num = num[:-2]
    if num:
        non_local_by_num.setdefault(num, []).append(r)

with open("raw/list_locals.json", encoding="utf-8") as f:
    import json
    directory_lus = {r["LU"] for r in json.load(f)}

print(f'{"LU":6}{"Members":>9}{"Receipts":>12}{"Form":>6}{"City":20}{"St":4}{"PD_Covered_To":16}  Note')
for lu in UNMATCHED_LU:
    r = olms_by_lu.get(lu)
    if not r:
        print(f"{lu}: not found in OLMS file (unexpected)")
        continue
    members = r["MEMBERS"]
    receipts = r["TTL_RECEIPTS"]
    form = r["FORM_TYPE"]
    city = r["CITY"]
    state = r["STATE"]
    pd = r["PD_COVERED_TO"]

    note_parts = []
    # is this LU number also present as a non-local entity designation?
    nl_matches = non_local_by_num.get(lu)
    if nl_matches:
        desigs = ", ".join(f'{m["DESIG_NAME"].strip()} ({m["UNIT_NAME"] or m["CITY"]})' for m in nl_matches)
        note_parts.append(f"ALSO a non-local entity: {desigs}")

    try:
        m_val = float(members) if members.strip() else 0.0
    except ValueError:
        m_val = 0.0

    in_directory = lu in directory_lus
    if not in_directory and m_val > 0:
        note_parts.append("LIKELY RECENT MERGER (nonzero members, absent from live directory)")
    elif not in_directory and m_val == 0:
        note_parts.append("zero/blank members, absent from directory (possibly defunct/administrative)")
    elif in_directory:
        note_parts.append("UNEXPECTED: LU present in directory but flagged unmatched")

    note = "; ".join(note_parts) if note_parts else ""
    print(f'{lu:6}{members:>9}{receipts:>12}{form:>6}{city:20}{state:4}{pd:16}  {note}')
