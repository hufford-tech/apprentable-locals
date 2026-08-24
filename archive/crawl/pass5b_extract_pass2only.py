import csv
import datetime
import json
import os
from collections import Counter

from scrape_lib2 import call_extraction
from pass2_crawl_locals import STATE_PATH, LOCAL_DIR

VALIDATION_PATH = "out/url_validation.csv"
EXTRACTED_JSONL = "raw/scrape/extracted_pass2only.jsonl"
OUT_CSV = "out/extraction_pass2only.csv"
PAGE_CHAR_CAP = 8000
BOILERPLATE_MIN_FRACTION = 0.5  # a line repeated on this fraction of a local's pages is dropped

os.makedirs("raw/scrape", exist_ok=True)

CURRENT_YEAR = datetime.date.today().year


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


def strip_boilerplate(pages):
    """Drop lines repeated across >= BOILERPLATE_MIN_FRACTION of this local's own pages
    (nav/footer/menu boilerplate), then cap each page at PAGE_CHAR_CAP chars."""
    if len(pages) < 2:
        return [(u, md[:PAGE_CHAR_CAP]) for u, md in pages]

    line_page_counts = Counter()
    per_page_lines = []
    for url, md in pages:
        lines = md.split("\n")
        per_page_lines.append(lines)
        for line in set(l.strip() for l in lines if l.strip()):
            line_page_counts[line] += 1

    threshold = max(2, int(len(pages) * BOILERPLATE_MIN_FRACTION))
    boilerplate = {line for line, count in line_page_counts.items() if count >= threshold}

    out = []
    for (url, md), lines in zip(pages, per_page_lines):
        kept = [l for l in lines if l.strip() not in boilerplate]
        cleaned = "\n".join(kept).strip()
        out.append((url, cleaned[:PAGE_CHAR_CAP]))
    return out


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
                    done_lus.add(json.loads(line)["lu_number"])
        print(f"Resuming: {len(done_lus)} already extracted")

    out_f = open(EXTRACTED_JSONL, "a", encoding="utf-8")

    processed = 0
    failures = []
    total_chars_before = 0
    total_chars_after = 0
    for lu in target_lus:
        if lu in done_lus:
            continue
        v = validation_rows.get(lu, {})
        info = locals_info.get(lu, {})
        state = local_state.get(lu, {})

        raw_pages = load_local_pages(lu)
        if not raw_pages:
            failures.append((lu, "no pages collected"))
            processed += 1
            continue

        total_chars_before += sum(len(md) for _, md in raw_pages)
        pages = strip_boilerplate(raw_pages)
        total_chars_after += sum(len(md) for _, md in pages)

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
    if total_chars_before:
        print(f"Boilerplate-strip + cap: {total_chars_before:,} chars -> {total_chars_after:,} chars "
              f"({100 * (1 - total_chars_after / total_chars_before):.1f}% reduction)")
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
