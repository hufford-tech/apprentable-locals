import csv
import json
import os

from scrape_lib2 import fc_client, with_retry, credits_remaining, is_shared_host
from pass2_crawl_locals import slugify, STATE_PATH

JATC_DIR = "raw/crawl/jatc"
JATC_STATE_PATH = "out/jatc_crawl_state.json"
LOCAL_TO_JATC_PATH = "out/local_to_jatc.csv"

os.makedirs(JATC_DIR, exist_ok=True)


def save_page(domain, url, md):
    d = os.path.join(JATC_DIR, domain.replace("/", "_"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, slugify(url) + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(url + "\n---\n" + md)


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")

    with open(STATE_PATH, encoding="utf-8") as f:
        local_state = json.load(f)

    domain_to_locals = {}
    domain_example_url = {}
    for lu, v in local_state.items():
        for dom, url in v.get("external_domains", {}).items():
            domain_to_locals.setdefault(dom, []).append(lu)
            domain_example_url.setdefault(dom, url)

    print(f"Distinct external domains across all locals: {len(domain_to_locals)}")

    jatc_state = {}
    if os.path.exists(JATC_STATE_PATH):
        with open(JATC_STATE_PATH, encoding="utf-8") as f:
            jatc_state = json.load(f)
        print(f"Resuming: {len(jatc_state)} domains already crawled")

    processed = 0
    zero_yield_domains = []
    for dom, example_url in domain_example_url.items():
        if dom in jatc_state:
            continue

        if is_shared_host(dom):
            doc, err = with_retry(fc_client().scrape, example_url, formats=["markdown", "links"], only_main_content=False)
            if err or doc is None:
                jatc_state[dom] = {"pages": [], "error": err, "shared_host": True}
                zero_yield_domains.append(dom)
            else:
                save_page(dom, example_url, doc.markdown or "")
                jatc_state[dom] = {"pages": [example_url], "error": None, "shared_host": True}
        else:
            job, err = with_retry(
                fc_client().crawl, example_url,
                limit=25, only_main_content=False, formats=["markdown", "links"],
                allow_external_links=False, sitemap="skip",
            )
            if err or job is None or not job.data:
                jatc_state[dom] = {"pages": [], "error": err, "shared_host": False}
                zero_yield_domains.append(dom)
            else:
                pages = []
                for d in job.data:
                    page_url = d.metadata.url if d.metadata else None
                    if not page_url:
                        continue
                    save_page(dom, page_url, d.markdown or "")
                    pages.append(page_url)
                jatc_state[dom] = {"pages": pages, "error": None, "shared_host": False}

        processed += 1
        if processed % 25 == 0:
            with open(JATC_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(jatc_state, f, indent=2)
            print(f"  [checkpoint] {processed} domains processed this run, credits remaining: {credits_remaining()}")

    with open(JATC_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(jatc_state, f, indent=2)

    with open(LOCAL_TO_JATC_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lu_number", "jatc_domain", "page_count"])
        for dom, lus in domain_to_locals.items():
            page_count = len(jatc_state.get(dom, {}).get("pages", []))
            for lu in lus:
                w.writerow([lu, dom, page_count])

    end_credits = credits_remaining()
    print(f"\nDone. Domains processed this run: {processed}  Credits used this run: {start_credits - end_credits}")
    print(f"Zero-yield domains (candidates for Pass 4 stealth retry): {len(zero_yield_domains)}")
    for d in zero_yield_domains:
        print(f"  {d}: {jatc_state[d].get('error')}")


if __name__ == "__main__":
    main()
