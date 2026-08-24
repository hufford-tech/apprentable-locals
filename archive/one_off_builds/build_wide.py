import csv
import json
import os

RAW = "raw"
OUT = "out"
os.makedirs(OUT, exist_ok=True)

with open(f"{RAW}/list_locals.json", encoding="utf-8") as f:
    lu_by_id = {r["ID"]: r["LU"] for r in json.load(f)}

with open(f"{RAW}/members_repaired_rows.json", encoding="utf-8") as f:
    repaired_member_rows = json.load(f)

# Reassemble repaired Members back into per-row dicts (row_id -> fields)
member_rows_by_local = {}  # local_id -> {row_id: {field: value}}
for r in repaired_member_rows:
    lid = r["local_union_id"]
    rid = r["row_id"]
    member_rows_by_local.setdefault(lid, {}).setdefault(rid, {"local_union_id": lid, "lu_number": r["lu_number"], "row_id": rid, "line_raw": r["line_raw"]})
    member_rows_by_local[lid][rid][r["field_name"]] = r["field_value"]

locals_rows = []
addresses_rows = []
phones_rows = []
emails_rows = []
officers_rows = []
trade_class_rows = []

for local_id, lu in lu_by_id.items():
    path = f"{RAW}/locals/{local_id}.json"
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    lu_fields = {}          # LocalUnion table fields (CharterCity, CharterState, LU_SC, Meets, Website)
    addr_rows_this_local = []
    phone_rows_this_local = []
    email_rows_this_local = []
    trade_classes_desc = ""

    for rec in records:
        tn = rec.get("tableName", "")
        row_id = rec.get("idFieldValue", "")
        names = (rec.get("editFieldNames") or "").split("|")
        values = (rec.get("editFieldValues") or "").split("|")
        if tn == "Members":
            continue  # handled separately from repaired data
        if len(names) != len(values):
            continue  # already logged as mismatch elsewhere; skip for wide tables
        fields = dict(zip(names, values))

        if tn == "LocalUnion":
            lu_fields.update(fields)
        elif tn == "Addresses":
            existing = next((a for a in addr_rows_this_local if a["row_id"] == row_id), None)
            if existing is None:
                existing = {"local_union_id": local_id, "lu_number": lu, "row_id": row_id}
                addr_rows_this_local.append(existing)
            existing.update(fields)
        elif tn == "Phones":
            existing = next((p for p in phone_rows_this_local if p["row_id"] == row_id), None)
            if existing is None:
                existing = {"local_union_id": local_id, "lu_number": lu, "row_id": row_id}
                phone_rows_this_local.append(existing)
            existing.update(fields)
        elif tn == "Emails":
            existing = next((e for e in email_rows_this_local if e["row_id"] == row_id), None)
            if existing is None:
                existing = {"local_union_id": local_id, "lu_number": lu, "row_id": row_id}
                email_rows_this_local.append(existing)
            existing.update(fields)
        elif tn == "TradeClasses":
            trade_classes_desc = fields.get("TradeClassDesc", "")

    addresses_rows.extend(addr_rows_this_local)
    phones_rows.extend(phone_rows_this_local)
    emails_rows.extend(email_rows_this_local)

    for code in [c.strip() for c in trade_classes_desc.split(",") if c.strip()]:
        trade_class_rows.append({"local_union_id": local_id, "lu_number": lu, "trade_class_code": code})

    # Officers from repaired Members
    for row_id, mrec in member_rows_by_local.get(local_id, {}).items():
        officers_rows.append({
            "local_union_id": local_id,
            "lu_number": lu,
            "row_id": row_id,
            "fname": mrec.get("fname", ""),
            "mi": mrec.get("mi", ""),
            "lname": mrec.get("lname", ""),
            "suffix": mrec.get("suffix", ""),
            "pos": mrec.get("pos", ""),
            "member_id": mrec.get("bs.MemberID", ""),
            "bm": mrec.get("bs.BM", ""),
            "pres": mrec.get("bs.PRES", ""),
            "fs": mrec.get("bs.FS", ""),
            "rs": mrec.get("bs.RS", ""),
            "brother_sister": mrec.get("bs.BrotherSister", ""),
            "addr1": mrec.get("bs.addr1", ""),
            "addr2": mrec.get("bs.addr2", ""),
            "addr3": mrec.get("bs.addr3", ""),
            "city": mrec.get("bs.city", ""),
            "state": mrec.get("bs.state", ""),
            "zip": mrec.get("bs.zip", ""),
            "line_raw": mrec.get("line_raw", ""),
        })

    primary_addr = addr_rows_this_local[0] if addr_rows_this_local else {}
    primary_phone = phone_rows_this_local[0] if phone_rows_this_local else {}
    primary_email = email_rows_this_local[0] if email_rows_this_local else {}

    locals_rows.append({
        "local_union_id": local_id,
        "lu_number": lu,
        "charter_city": lu_fields.get("CharterCity", ""),
        "charter_state": lu_fields.get("CharterState", ""),
        "lu_sc": lu_fields.get("LU_SC", ""),
        "meets": lu_fields.get("Meets", ""),
        "website": lu_fields.get("Website", ""),
        "primary_address1": primary_addr.get("Address1", ""),
        "primary_address_name": primary_addr.get("Name", ""),
        "primary_city": primary_addr.get("City", ""),
        "primary_state": primary_addr.get("[State]", ""),
        "primary_zip": primary_addr.get("Zip", ""),
        "primary_phone": primary_phone.get("PhoneNo", ""),
        "primary_email": primary_email.get("Email", ""),
    })


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


write_csv(f"{OUT}/locals.csv", locals_rows, [
    "local_union_id", "lu_number", "charter_city", "charter_state", "lu_sc",
    "meets", "website", "primary_address1", "primary_address_name",
    "primary_city", "primary_state", "primary_zip", "primary_phone", "primary_email",
])
write_csv(f"{OUT}/addresses.csv", addresses_rows, [
    "local_union_id", "lu_number", "row_id", "Name", "Address1", "Address2", "City", "[State]", "Zip",
])
write_csv(f"{OUT}/phones.csv", phones_rows, [
    "local_union_id", "lu_number", "row_id", "PhoneNo",
])
write_csv(f"{OUT}/emails.csv", emails_rows, [
    "local_union_id", "lu_number", "row_id", "Email",
])
write_csv(f"{OUT}/officers.csv", officers_rows, [
    "local_union_id", "lu_number", "row_id", "fname", "mi", "lname", "suffix", "pos",
    "member_id", "bm", "pres", "fs", "rs", "brother_sister",
    "addr1", "addr2", "addr3", "city", "state", "zip", "line_raw",
])
write_csv(f"{OUT}/trade_classes.csv", trade_class_rows, [
    "local_union_id", "lu_number", "trade_class_code",
])

print(f"locals.csv: {len(locals_rows)} rows")
print(f"addresses.csv: {len(addresses_rows)} rows")
print(f"phones.csv: {len(phones_rows)} rows")
print(f"emails.csv: {len(emails_rows)} rows")
print(f"officers.csv: {len(officers_rows)} rows")
print(f"trade_classes.csv: {len(trade_class_rows)} rows")
