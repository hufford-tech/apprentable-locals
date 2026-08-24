# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/build_contact_validation.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

"""out/contact_validation.csv -- cross-validate the IBEW directory's phone/email
fields (out/emails.csv, out/phones.csv) against what the crawler independently
extracted per local (out/extraction_v2.csv contact_email/contact_phone),
frontend task 4. 15.9% of directory website fields were wrong; check whether
phones/emails are similarly unreliable, for free, since both sources already
exist on disk.
"""
import csv
import re
from collections import defaultdict

csv.field_size_limit(10_000_000)


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def digits(phone):
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


targets = load("out/targets_with_population.csv")
lu_list = [t["lu_number"] for t in targets]
lid_by_lu = {t["lu_number"]: t["local_union_id"] for t in targets}

# directory: lowest row_id per local = primary listed contact
dir_email = {}
by_local = defaultdict(list)
for r in load("out/emails.csv"):
    by_local[r["lu_number"]].append(r)
for lu, rs in by_local.items():
    rs.sort(key=lambda r: int(r["row_id"]))
    dir_email[lu] = rs[0]["Email"].strip()

dir_phone = {}
by_local = defaultdict(list)
for r in load("out/phones.csv"):
    by_local[r["lu_number"]].append(r)
for lu, rs in by_local.items():
    rs.sort(key=lambda r: int(r["row_id"]))
    dir_phone[lu] = rs[0]["PhoneNo"].strip()

crawled = {r["lu_number"]: r for r in load("out/extraction_v2.csv")}

rows = []
email_stats = defaultdict(int)
phone_stats = defaultdict(int)

for lu in lu_list:
    lid = lid_by_lu[lu]
    d_email = dir_email.get(lu, "")
    c_email = (crawled.get(lu, {}).get("contact_email") or "").strip()
    d_phone = dir_phone.get(lu, "")
    c_phone = (crawled.get(lu, {}).get("contact_phone") or "").strip()

    if d_email and c_email:
        email_agreement = "match" if d_email.lower() == c_email.lower() else "mismatch"
    elif d_email:
        email_agreement = "directory_only"
    elif c_email:
        email_agreement = "crawled_only"
    else:
        email_agreement = "neither"

    if d_phone and c_phone:
        phone_agreement = "match" if digits(d_phone) == digits(c_phone) else "mismatch"
    elif d_phone:
        phone_agreement = "directory_only"
    elif c_phone:
        phone_agreement = "crawled_only"
    else:
        phone_agreement = "neither"

    email_stats[email_agreement] += 1
    phone_stats[phone_agreement] += 1

    # recommended: prefer crawled when they disagree (it came from the local's
    # own live site); otherwise take whichever is present.
    if email_agreement == "mismatch":
        rec_email, rec_email_basis = c_email, "crawled (disagreement, live-site source preferred)"
    elif c_email:
        rec_email, rec_email_basis = c_email, "crawled" if email_agreement != "directory_only" else "directory (crawled absent)"
    else:
        rec_email, rec_email_basis = d_email, "directory (crawled absent)"

    if phone_agreement == "mismatch":
        rec_phone, rec_phone_basis = c_phone, "crawled (disagreement, live-site source preferred)"
    elif c_phone:
        rec_phone, rec_phone_basis = c_phone, "crawled" if phone_agreement != "directory_only" else "directory (crawled absent)"
    else:
        rec_phone, rec_phone_basis = d_phone, "directory (crawled absent)"

    rows.append({
        "local_union_id": lid,
        "lu_number": lu,
        "directory_email": d_email,
        "crawled_email": c_email,
        "email_agreement": email_agreement,
        "directory_phone": d_phone,
        "crawled_phone": c_phone,
        "phone_agreement": phone_agreement,
        "recommended_value": f"email={rec_email} | phone={rec_phone}",
        "recommendation_basis": f"email: {rec_email_basis}; phone: {rec_phone_basis}",
    })

with open("out/contact_validation.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["local_union_id", "lu_number", "directory_email", "crawled_email",
                  "email_agreement", "directory_phone", "crawled_phone", "phone_agreement",
                  "recommended_value", "recommendation_basis"]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)

both_present_email = email_stats["match"] + email_stats["mismatch"]
both_present_phone = phone_stats["match"] + phone_stats["mismatch"]
email_mismatch_rate = 100 * email_stats["mismatch"] / both_present_email if both_present_email else 0
phone_mismatch_rate = 100 * phone_stats["mismatch"] / both_present_phone if both_present_phone else 0

print(f"targets: {len(lu_list)}")
print(f"email agreement: {dict(email_stats)}  (mismatch rate where both present: {email_mismatch_rate:.1f}%)")
print(f"phone agreement: {dict(phone_stats)}  (mismatch rate where both present: {phone_mismatch_rate:.1f}%)")
baseline = 15.9
combined_n = both_present_email + both_present_phone
combined_mismatch = email_stats["mismatch"] + phone_stats["mismatch"]
combined_rate = 100 * combined_mismatch / combined_n if combined_n else 0
print(f"combined phone+email mismatch rate: {combined_rate:.1f}% vs {baseline}% website-field baseline")
if combined_rate > baseline:
    print("ABOVE baseline: the directory is worse than the website-field check implied.")
else:
    print("At or below baseline.")
