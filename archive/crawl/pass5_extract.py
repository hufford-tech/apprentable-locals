import csv
import json
import os
import datetime

from scrape_lib2 import call_extraction
from pass2_crawl_locals import STATE_PATH, LOCAL_DIR, slugify

VALIDATION_PATH = "out/url_validation.csv"
JATC_STATE_PATH = "out/jatc_crawl_state.json"
JATC_DIR = "raw/crawl/jatc"
EXTRACTED_JSONL = "raw/scrape/extracted.jsonl"
OUT_CSV = "out/apprenticeship_data.csv"

os.makedirs("raw/scrape", exist_ok=True)

CURRENT_YEAR = datetime.date.today().year


def read_page(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    parts = content.split("\n---\n", 1)
    return parts[1] if len(parts) == 2 else content


def load_local_pages(lu):
    d = os.path.join(LOCAL_DIR, lu)
    pages = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            path = os.path.join(d, fn)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            parts = content.split("\n---\n", 1)
            if len(parts) == 2:
                url, md = parts
                pages.append((url.strip(), md))
    return pages


def load_jatc_pages(domain):
    d = os.path.join(JATC_DIR, domain.replace("/", "_"))
    pages = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            path = os.path.join(d, fn)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            parts = content.split("\n---\n", 1)
            if len(parts) == 2:
                url, md = parts
                pages.append((url.strip(), md))
    return pages


def main():
    with open(VALIDATION_PATH, encoding="utf-8") as f:
        validation_rows = {r["lu_number"]: r for r in csv.DictReader(f)}

    with open(STATE_PATH, encoding="utf-8") as f:
        local_state = json.load(f)

    with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
        locals_info = {r["lu_number"]: r for r in csv.DictReader(f)}

    with open("out/scrape_targets.csv", encoding="utf-8") as f:
        target_lus = [r["lu_number"] for r in csv.DictReader(f)]

    done_lus = set()
    if os.path.exists(EXTRACTED_JSONL):
        with open(EXTRACTED_JSONL, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    done_lus.add(rec["lu_number"])
        print(f"Resuming: {len(done_lus)} already extracted")

    out_f = open(EXTRACTED_JSONL, "a", encoding="utf-8")

    processed = 0
    failures = []
    for lu in target_lus:
        if lu in done_lus:
            continue
        v = validation_rows.get(lu, {})
        info = locals_info.get(lu, {})
        state = local_state.get(lu, {})

        pages = load_local_pages(lu)
        for dom in state.get("external_domains", {}):
            pages.extend(load_jatc_pages(dom))

        if not pages:
            failures.append((lu, "no pages collected"))
            processed += 1
            continue

        website_corrected = str(v.get("disagreed", "")) == "True"
        original_website = info.get("website", "")

        try:
            extracted, usage = call_extraction(
                lu, info.get("charter_city", ""), pages,
                current_year=CURRENT_YEAR,
                website_corrected=website_corrected,
                original_website=original_website,
                state_dol_url="",
            )
        except Exception as e:
            failures.append((lu, str(e)))
            processed += 1
            continue

        record = {"lu_number": lu, **extracted}
        out_f.write(json.dumps(record) + "\n")
        out_f.flush()
        processed += 1

        if processed % 25 == 0:
            print(f"  [checkpoint] {processed} extracted this run")

    out_f.close()
    print(f"\nDone. Extracted this run: {processed - len(failures)}  Failures: {len(failures)}")
    for lu, err in failures[:20]:
        print(f"  LU {lu}: {err}")

    # ---- Build final CSV ----
    all_records = []
    with open(EXTRACTED_JSONL, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_records.append(json.loads(line))

    fieldnames = [
        "lu_number", "has_apprenticeship", "program_name", "jatc_name", "jatc_domain",
        "application_url", "accepting_applications", "window_count",
        "windows_json", "occupations", "min_age", "min_education",
        "citizenship_required", "aptitude_test", "interview_required",
        "math_requirement", "other_requirements", "contact_email", "contact_phone",
        "application_method", "has_notification_list", "notification_instructions",
        "state_dol_url", "website_corrected", "original_website",
        "status_as_of_date", "content_year", "is_stale", "confidence",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_records:
            row = {k: r.get(k, "") for k in fieldnames if k not in ("window_count", "windows_json")}
            windows = r.get("windows", [])
            row["window_count"] = len(windows)
            row["windows_json"] = json.dumps(windows)
            for k in ("occupations", "other_requirements"):
                row[k] = json.dumps(r.get(k, []))
            w.writerow(row)

    print(f"Wrote {OUT_CSV}: {len(all_records)} rows")


if __name__ == "__main__":
    main()
