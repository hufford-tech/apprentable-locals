import csv
import datetime
import json
import os

from scrape_lib2 import call_extraction, prefilter_pages
from pass2_crawl_locals import LOCAL_DIR

TEN = ["136", "505", "558", "1547", "570", "340", "569", "113", "349", "606"]
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
    with open("out/url_validation.csv", encoding="utf-8") as f:
        validation_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
    with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
        locals_info = {r["lu_number"]: r for r in csv.DictReader(f)}
    with open("raw/scrape/extracted_pass2only.jsonl", encoding="utf-8") as f:
        before = {}
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["lu_number"] in TEN:
                    before[r["lu_number"]] = r

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    after = {}
    for lu in TEN:
        raw_pages = load_local_pages(lu)
        filtered = prefilter_pages(raw_pages)
        v = validation_rows.get(lu, {})
        info = locals_info.get(lu, {})
        website_corrected = str(v.get("disagreed", "")) == "True"
        original_website = info.get("website", "")
        try:
            extracted, usage = call_extraction(
                lu, info.get("charter_city", ""), filtered,
                current_year=CURRENT_YEAR,
                website_corrected=website_corrected, original_website=original_website,
                state_dol_url="",
            )
        except Exception as e:
            print(f"LU {lu}: FAILED -- {e}")
            after[lu] = {"accepting_applications": f"ERROR: {e}"}
            continue
        after[lu] = extracted
        total_input += usage.input_tokens
        total_output += usage.output_tokens
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        total_cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        print(f"LU {lu}: cache_read={getattr(usage,'cache_read_input_tokens',0)} "
              f"cache_write={getattr(usage,'cache_creation_input_tokens',0)} "
              f"input={usage.input_tokens} output={usage.output_tokens}")

    print(f"\n{'LU':>6}  {'BEFORE':<10} {'AFTER':<10}")
    for lu in TEN:
        b = before.get(lu, {}).get("accepting_applications", "MISSING")
        a = after.get(lu, {}).get("accepting_applications", "MISSING")
        flag = "  <-- CHANGED" if b != a else ""
        print(f"{lu:>6}  {b:<10} {a:<10}{flag}")

    print(f"\nTotal tokens: input={total_input:,} output={total_output:,} "
          f"cache_read={total_cache_read:,} cache_write={total_cache_write:,}")
    # standard (non-batch) pricing for claude-sonnet-4-6: $3/MTok in, $15/MTok out,
    # cache read $0.30/MTok, cache write $3.75/MTok
    cost = (
        (total_input / 1_000_000) * 3.00
        + (total_output / 1_000_000) * 15.00
        + (total_cache_read / 1_000_000) * 0.30
        + (total_cache_write / 1_000_000) * 3.75
    )
    print(f"Estimated cost (standard, non-batch): ${cost:.4f}")

    with open("raw/scrape/fewshot_test_10.json", "w", encoding="utf-8") as f:
        json.dump(after, f, indent=2)


if __name__ == "__main__":
    main()
