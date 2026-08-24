import csv
import datetime
import json
import os
import time

from scrape_lib2 import (
    anthropic_client, build_extraction_batch_request, prefilter_pages,
    parse_extraction_text,
)
from pass2_crawl_locals import LOCAL_DIR

VALIDATION_PATH = "out/url_validation.csv"
STATE_PATH = "out/local_crawl_state.json"
EXTRACTED_JSONL = "raw/scrape/extracted_pass2only.jsonl"
OUT_CSV = "out/extraction_pass2only.csv"
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


def main():
    with open(VALIDATION_PATH, encoding="utf-8") as f:
        validation_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
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
    remaining = [lu for lu in target_lus if lu not in done_lus]
    print(f"Already extracted: {len(done_lus)}  Remaining: {len(remaining)}")

    requests = []
    pages_before_total = 0
    pages_after_total = 0
    no_page_lus = []
    lu_meta = {}
    for lu in remaining:
        raw_pages = load_local_pages(lu)
        if not raw_pages:
            no_page_lus.append(lu)
            continue
        filtered = prefilter_pages(raw_pages)
        pages_before_total += len(raw_pages)
        pages_after_total += len(filtered)

        v = validation_rows.get(lu, {})
        info = locals_info.get(lu, {})
        website_corrected = str(v.get("disagreed", "")) == "True"
        original_website = info.get("website", "")
        custom_id = f"lu-{lu}"
        lu_meta[custom_id] = lu
        req = build_extraction_batch_request(
            custom_id, lu, info.get("charter_city", ""), filtered, CURRENT_YEAR,
            website_corrected=website_corrected, original_website=original_website,
            state_dol_url="",
        )
        requests.append(req)

    n_batch_locals = len(requests)
    avg_before = pages_before_total / n_batch_locals if n_batch_locals else 0
    avg_after = pages_after_total / n_batch_locals if n_batch_locals else 0
    print(f"No-pages-collected (skipped, no batch call): {len(no_page_lus)} {no_page_lus}")
    print(f"Batch-eligible locals: {n_batch_locals}")
    print(f"Avg pages/local BEFORE prefilter: {avg_before:.1f}")
    print(f"Avg pages/local AFTER prefilter:  {avg_after:.1f}")

    if not requests:
        print("Nothing to submit.")
        return

    client = anthropic_client()
    batch = client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id}, status={batch.processing_status}")

    while True:
        b = client.messages.batches.retrieve(batch.id)
        counts = b.request_counts
        print(f"  [poll] status={b.processing_status} "
              f"processing={counts.processing} succeeded={counts.succeeded} "
              f"errored={counts.errored} canceled={counts.canceled} expired={counts.expired}")
        if b.processing_status == "ended":
            break
        time.sleep(20)

    out_f = open(EXTRACTED_JSONL, "a", encoding="utf-8")
    succeeded = 0
    failed = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read = 0
    total_cache_write = 0
    for entry in client.messages.batches.results(batch.id):
        lu = lu_meta.get(entry.custom_id, entry.custom_id.replace("lu-", ""))
        if entry.result.type != "succeeded":
            failed.append((lu, entry.result.type))
            continue
        msg = entry.result.message
        try:
            extracted = parse_extraction_text(msg.content[0].text)
        except Exception as e:
            failed.append((lu, f"parse error: {e}"))
            continue
        record = {"lu_number": lu, **extracted}
        out_f.write(json.dumps(record) + "\n")
        succeeded += 1
        usage = msg.usage
        total_input_tokens += usage.input_tokens
        total_output_tokens += usage.output_tokens
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        total_cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
    out_f.close()

    print(f"\nBatch done. Succeeded: {succeeded}  Failed: {len(failed)}")
    for lu, err in failed[:20]:
        print(f"  LU {lu}: {err}")
    print(f"Token usage: input={total_input_tokens:,} output={total_output_tokens:,} "
          f"cache_read={total_cache_read:,} cache_write={total_cache_write:,}")

    # Anthropic batch pricing: 50% of standard per-token rates.
    # claude-sonnet-4-6 standard: $3/MTok input, $15/MTok output (cache read $0.30/MTok, cache write $3.75/MTok)
    # Batch = 50% of all of those.
    cost = (
        (total_input_tokens / 1_000_000) * 3.00 * 0.5
        + (total_output_tokens / 1_000_000) * 15.00 * 0.5
        + (total_cache_read / 1_000_000) * 0.30 * 0.5
        + (total_cache_write / 1_000_000) * 3.75 * 0.5
    )
    print(f"Estimated actual cost (batch, 50% rates): ${cost:.4f}")

    # ---- Rebuild final CSV from the full jsonl (172 prior + new batch results) ----
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

    print(f"Wrote {OUT_CSV}: {len(all_records)} rows total")


if __name__ == "__main__":
    main()
