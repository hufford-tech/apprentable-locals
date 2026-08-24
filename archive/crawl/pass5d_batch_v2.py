import csv
import datetime
import json
import os
import time

from scrape_lib2 import (
    anthropic_client, build_extraction_batch_request, prefilter_pages,
    parse_extraction_text, ExtractionIncompleteError,
)
from pass2_crawl_locals import LOCAL_DIR

EXTRACTED_JSONL = "raw/scrape/extracted_v2.jsonl"
OUT_CSV = "out/extraction_v2.csv"
CURRENT_YEAR = datetime.date.today().year


def load_pages_dir(d):
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
    with open("out/url_validation.csv", encoding="utf-8") as f:
        validation_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
        locals_info = {r["lu_number"]: r for r in csv.DictReader(f)}
    with open("out/scrape_targets.csv", encoding="utf-8") as f:
        target_lus = [r["lu_number"] for r in csv.DictReader(f)]
    with open("out/local_crawl_state.json", encoding="utf-8") as f:
        local_state = json.load(f)
    with open("out/jatc_crawl_state.json", encoding="utf-8") as f:
        jatc_state = json.load(f)

    requests = []
    lu_meta = {}
    pages_before_total = 0
    pages_after_total = 0
    no_page_lus = []

    for lu in target_lus:
        own_pages = load_pages_dir(os.path.join(LOCAL_DIR, lu))
        jatc_pages = []
        for dom in local_state.get(lu, {}).get("external_domains", {}):
            if dom in jatc_state and jatc_state[dom].get("pages"):
                jatc_pages.extend(load_pages_dir(os.path.join("raw/crawl/jatc", dom.replace("/", "_"))))
        all_pages = own_pages + jatc_pages
        if not all_pages:
            no_page_lus.append(lu)
            continue
        filtered = prefilter_pages(all_pages)
        pages_before_total += len(all_pages)
        pages_after_total += len(filtered)

        v = validation_rows.get(lu, {})
        info = locals_info.get(lu, {})
        custom_id = f"lu-{lu}"
        lu_meta[custom_id] = lu
        req = build_extraction_batch_request(
            custom_id, lu, info.get("charter_city", ""), filtered, CURRENT_YEAR,
            website_corrected=str(v.get("disagreed", "")) == "True",
            original_website=info.get("website", ""),
            state_dol_url="",
        )
        requests.append(req)

    n = len(requests)
    print(f"No-pages-collected (skipped): {len(no_page_lus)} {no_page_lus}")
    print(f"Batch-eligible locals: {n}")
    if n:
        print(f"Avg pages/local BEFORE prefilter: {pages_before_total/n:.1f}")
        print(f"Avg pages/local AFTER prefilter:  {pages_after_total/n:.1f}")

    client = anthropic_client()
    batch = client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id}, status={batch.processing_status}")

    while True:
        b = client.messages.batches.retrieve(batch.id)
        c = b.request_counts
        print(f"  [poll] status={b.processing_status} processing={c.processing} "
              f"succeeded={c.succeeded} errored={c.errored} canceled={c.canceled} expired={c.expired}")
        if b.processing_status == "ended":
            break
        time.sleep(20)

    out_f = open(EXTRACTED_JSONL, "w", encoding="utf-8")
    succeeded = 0
    failed = []
    total_input = total_output = total_cache_read = total_cache_write = 0
    for entry in client.messages.batches.results(batch.id):
        lu = lu_meta.get(entry.custom_id, entry.custom_id.replace("lu-", ""))
        if entry.result.type != "succeeded":
            failed.append((lu, entry.result.type))
            continue
        msg = entry.result.message
        try:
            extracted = parse_extraction_text(msg.content[0].text, stop_reason=msg.stop_reason)
        except ExtractionIncompleteError as e:
            failed.append((lu, f"truncated: {e}"))
            continue
        except Exception as e:
            failed.append((lu, f"parse error: {e}"))
            continue
        record = {"lu_number": lu, **extracted}
        out_f.write(json.dumps(record) + "\n")
        succeeded += 1
        usage = msg.usage
        total_input += usage.input_tokens
        total_output += usage.output_tokens
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        total_cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
    out_f.close()

    print(f"\nBatch done. Succeeded: {succeeded}  Failed: {len(failed)}")
    for lu, err in failed:
        print(f"  LU {lu}: {err}")
    print(f"Token usage: input={total_input:,} output={total_output:,} "
          f"cache_read={total_cache_read:,} cache_write={total_cache_write:,}")

    cost = (
        (total_input / 1_000_000) * 3.00 * 0.5
        + (total_output / 1_000_000) * 15.00 * 0.5
        + (total_cache_read / 1_000_000) * 0.30 * 0.5
        + (total_cache_write / 1_000_000) * 3.75 * 0.5
    )
    print(f"Estimated actual cost (batch, 50% rates): ${cost:.4f}")

    # ---- Build final CSV ----
    all_records = []
    with open(EXTRACTED_JSONL, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_records.append(json.loads(line))

    fieldnames = [
        "lu_number", "has_apprenticeship", "program_name", "jatc_name", "jatc_domain",
        "application_url", "windows_json", "window_count",
        "status_statements_json", "status_statement_count",
        "occupations", "min_age", "min_education",
        "citizenship_required", "aptitude_test", "interview_required",
        "math_requirement", "other_requirements", "contact_email", "contact_phone",
        "application_method", "has_notification_list", "notification_instructions",
        "state_dol_url", "website_corrected", "original_website",
        "page_last_updated", "content_year", "is_stale", "confidence",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_records:
            row = {k: r.get(k, "") for k in fieldnames
                   if k not in ("window_count", "windows_json", "status_statement_count", "status_statements_json")}
            windows = r.get("windows", [])
            statements = r.get("status_statements", [])
            row["window_count"] = len(windows)
            row["windows_json"] = json.dumps(windows)
            row["status_statement_count"] = len(statements)
            row["status_statements_json"] = json.dumps(statements)
            for k in ("occupations", "other_requirements"):
                row[k] = json.dumps(r.get(k, []))
            w.writerow(row)

    print(f"Wrote {OUT_CSV}: {len(all_records)} rows")


if __name__ == "__main__":
    main()
