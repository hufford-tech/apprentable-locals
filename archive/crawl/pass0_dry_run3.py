import json
import os
import pickle

from pass0_dry_run2 import load_targets, process_local, DRY_RUN_LUS
from scrape_lib2 import (
    fc_client, with_retry, credits_remaining, domain_of, is_shared_host,
    call_extraction,
)

CACHE_PATH = "raw/dry_run3_cache.pkl"


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")
    targets = load_targets()

    if os.path.exists(CACHE_PATH):
        print(f"Loading cached Firecrawl results from {CACHE_PATH} (skipping re-fetch)")
        with open(CACHE_PATH, "rb") as f:
            local_results = pickle.load(f)
    else:
        local_results = {}
        for lu in DRY_RUN_LUS:
            t = targets.get(lu)
            if not t:
                continue
            credits_before = credits_remaining()
            r = process_local(lu, t, credits_before)
            if r:
                local_results[lu] = {"target": t, **r}
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(local_results, f)
        print(f"Cached results to {CACHE_PATH}")

    print(f"\n{'='*70}\nPHASE 2: JATC / shared-host page collection\n{'='*70}")

    jatc_cache_path = "raw/dry_run3_jatc_cache.pkl"
    if os.path.exists(jatc_cache_path):
        print(f"Loading cached JATC page results from {jatc_cache_path} (skipping re-fetch)")
        with open(jatc_cache_path, "rb") as f:
            jatc_pages_by_domain = pickle.load(f)
        for lu, r in local_results.items():
            print(f"\n--- LU {lu}: {len(r['external_domains'])} external domain(s), all served from cache ---")
        _skip_phase2 = True
    else:
        jatc_pages_by_domain = {}  # domain -> list of (url, markdown)
        _skip_phase2 = False

    for lu, r in ([] if _skip_phase2 else local_results.items()):
        print(f"\n--- LU {lu}: resolving {len(r['external_domains'])} external domain(s) ---")
        for dom in r["external_domains"]:
            example_url = r["external_domain_urls"].get(dom)
            if dom in jatc_pages_by_domain:
                print(f"  {dom}: already fetched (shared by an earlier local), reusing")
                continue

            if is_shared_host(dom):
                print(f"  {dom}: SHARED HOST -- scraping exact URL only: {example_url}")
                doc, err = with_retry(fc_client().scrape, example_url, formats=["markdown", "links"], only_main_content=False)
                if err:
                    print(f"    SCRAPE FAILED: {err}")
                    jatc_pages_by_domain[dom] = []
                    continue
                jatc_pages_by_domain[dom] = [(example_url, doc.markdown or "")]
                print(f"    OK, markdown={len(doc.markdown or '')} chars")
            else:
                seed = example_url or f"https://{dom}"
                print(f"  {dom}: real JATC domain -- unrestricted crawl, limit=25, seed={seed}")
                job, err = with_retry(
                    fc_client().crawl, seed,
                    limit=25, only_main_content=False, formats=["markdown", "links"],
                    allow_external_links=False,
                )
                if err:
                    print(f"    CRAWL FAILED: {err}")
                    jatc_pages_by_domain[dom] = []
                    continue
                print(f"    status={job.status} total={job.total} completed={job.completed} "
                      f"credits_used={job.credits_used} pages_returned={len(job.data)}")
                pages = []
                for d in job.data:
                    page_url = d.metadata.url if d.metadata else "?"
                    pages.append((page_url, d.markdown or ""))
                    print(f"      - {page_url}  ({len(d.markdown or '')} chars)")
                jatc_pages_by_domain[dom] = pages

    if not _skip_phase2:
        with open(jatc_cache_path, "wb") as f:
            pickle.dump(jatc_pages_by_domain, f)
        print(f"Cached JATC results to {jatc_cache_path}")

    print(f"\n{'='*70}\nPHASE 3: EXTRACTION\n{'='*70}")

    extraction_results = {}
    for lu, r in local_results.items():
        t = r["target"]
        pages = list(r["pages_collected"])
        for dom in r["external_domains"]:
            pages.extend(jatc_pages_by_domain.get(dom, []))

        print(f"\n{'='*70}\nLU {lu} ({t['charter_city']}, {t['charter_state']}) -- extracting from {len(pages)} page(s)")
        print(f"{'='*70}")
        for url, md in pages:
            print(f"  page: {url}  ({len(md)} chars)")

        try:
            extracted, usage = call_extraction(
                lu, t["charter_city"], pages,
                website_corrected=False, original_website=t["website"], state_dol_url="",
            )
        except Exception as e:
            print(f"  EXTRACTION FAILED: {e}")
            continue

        extraction_results[lu] = extracted
        print(f"  token usage: input={usage.input_tokens} output={usage.output_tokens}")
        print("  EXTRACTED JSON:")
        print(json.dumps(extracted, indent=2))

    end_credits = credits_remaining()

    print(f"\n{'='*70}\nSUMMARY: application window fields across the 6 dry-run locals\n{'='*70}")
    real_date_count = 0
    desc_only_count = 0
    nothing_count = 0
    for lu, ex in extraction_results.items():
        has_open = bool(ex.get("app_window_open"))
        has_close = bool(ex.get("app_window_close"))
        has_desc = bool(ex.get("app_window_description"))
        if has_open or has_close:
            real_date_count += 1
            bucket = "REAL ISO DATE"
        elif has_desc:
            desc_only_count += 1
            bucket = "description only"
        else:
            nothing_count += 1
            bucket = "nothing"
        print(f"\nLU {lu} [{bucket}]")
        print(f"  app_window_open:        {ex.get('app_window_open')!r}")
        print(f"  app_window_close:       {ex.get('app_window_close')!r}")
        print(f"  app_window_description: {ex.get('app_window_description')!r}")
        print(f"  accepting_applications: {ex.get('accepting_applications')!r}")
        print(f"  application_method:     {ex.get('application_method')!r}")
        print(f"  application_cap:        {ex.get('application_cap')!r}")
        print(f"  evidence_quote:         {ex.get('evidence_quote')!r}")

    print(f"\nOf {len(extraction_results)}: {real_date_count} real ISO date, "
          f"{desc_only_count} description-only, {nothing_count} nothing.")
    print(f"\nTotal credits used this session: {start_credits - end_credits}  (start={start_credits} end={end_credits})")


if __name__ == "__main__":
    main()
