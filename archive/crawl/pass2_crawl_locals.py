import csv
import json
import os
import re

from scrape_lib2 import (
    fc_client, with_retry, credits_remaining, domain_of,
    fingerprint_platform, matches_keywords, matches_external_anchor_keywords,
    unionactive_page_value, extract_markdown_links, EXTERNAL_DOMAIN_KEYWORDS,
)

VALIDATION_PATH = "out/url_validation.csv"
LOCAL_DIR = "raw/crawl/local"
STATE_PATH = "out/local_crawl_state.json"

os.makedirs(LOCAL_DIR, exist_ok=True)


def slugify(url):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", url)
    return s[:120]


def save_page(lu, url, md):
    d = os.path.join(LOCAL_DIR, lu)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, slugify(url) + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(url + "\n---\n" + md)
    return path


def load_validation():
    with open(VALIDATION_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def process_local(lu, chosen_url, platform):
    """Returns dict: pages (list of (url, md) already saved to disk),
    external_domains (dict domain -> example_url)."""
    home_domain = domain_of(chosen_url)
    pages = []
    external_domain_urls = {}

    doc, err = with_retry(fc_client().scrape, chosen_url, formats=["markdown", "links"], only_main_content=False)
    if err:
        return {"error": f"homepage scrape failed: {err}", "pages": [], "external_domains": {}}
    md, links = doc.markdown or "", doc.links or []
    save_page(lu, chosen_url, md)
    pages.append(chosen_url)

    anchor_map_home = {}
    for text, url in extract_markdown_links(md):
        anchor_map_home.setdefault(url, text)
    for l in links:
        dom = domain_of(l)
        if dom and dom != home_domain:
            anchor_text = anchor_map_home.get(l, "")
            if any(k in dom for k in EXTERNAL_DOMAIN_KEYWORDS) or matches_external_anchor_keywords(anchor_text):
                external_domain_urls.setdefault(dom, l)

    if platform == "UnionActive":
        anchor_map = anchor_map_home
        seen_pages = set()
        matches = []
        for url in links:
            pv = unionactive_page_value(url)
            if pv is None:
                continue
            kw = matches_keywords(pv.replace("20", " ")) or matches_keywords(anchor_map.get(url, ""))
            if kw and url not in seen_pages:
                seen_pages.add(url)
                matches.append(url)
        matches = matches[:8]
        for url in matches:
            cdoc, cerr = with_retry(fc_client().scrape, url, formats=["markdown", "links"], only_main_content=False)
            if cerr:
                continue
            cmd = cdoc.markdown or ""
            save_page(lu, url, cmd)
            pages.append(url)
            c_anchor_map = {t: u for t, u in [(b, a) for a, b in extract_markdown_links(cmd)]}
            c_anchor_map2 = {}
            for text, u2 in extract_markdown_links(cmd):
                c_anchor_map2.setdefault(u2, text)
            for l in (cdoc.links or []):
                dom2 = domain_of(l)
                if dom2 and dom2 != home_domain:
                    if any(k in dom2 for k in EXTERNAL_DOMAIN_KEYWORDS) or matches_external_anchor_keywords(c_anchor_map2.get(l, "")):
                        external_domain_urls.setdefault(dom2, l)
    else:
        job, err = with_retry(
            fc_client().crawl, chosen_url,
            limit=25, only_main_content=False, formats=["markdown", "links"],
            allow_external_links=False, sitemap="skip",
        )
        if err:
            pass
        else:
            for d in job.data:
                page_url = d.metadata.url if d.metadata else None
                if not page_url or page_url == chosen_url:
                    continue
                pmd = d.markdown or ""
                save_page(lu, page_url, pmd)
                pages.append(page_url)
                p_anchor_map = {}
                for text, u2 in extract_markdown_links(pmd):
                    p_anchor_map.setdefault(u2, text)
                for l in (d.links or []):
                    dom = domain_of(l)
                    if dom and dom != home_domain:
                        if any(k in dom for k in EXTERNAL_DOMAIN_KEYWORDS) or matches_external_anchor_keywords(p_anchor_map.get(l, "")):
                            external_domain_urls.setdefault(dom, l)

    return {"error": None, "pages": pages, "external_domains": external_domain_urls}


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")
    rows = load_validation()
    print(f"Total locals: {len(rows)}")

    state = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
        print(f"Resuming: {len(state)} already crawled")

    processed = 0
    for r in rows:
        lu = r["lu_number"]
        if lu in state:
            continue
        chosen_url = r["chosen_url"]
        platform = r["platform"]
        if not chosen_url or platform == "ERROR":
            state[lu] = {"error": "no usable URL from Pass 1", "pages": [], "external_domains": {}}
            continue

        result = process_local(lu, chosen_url, platform)
        state[lu] = result
        processed += 1

        if processed % 25 == 0:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            print(f"  [checkpoint] {processed} processed this run, {len(state)} total, "
                  f"credits remaining: {credits_remaining()}")

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    end_credits = credits_remaining()
    print(f"\nDone. Processed this run: {processed}  Credits used this run: {start_credits - end_credits}")

    total_pages = sum(len(v.get("pages", [])) for v in state.values())
    total_domains = set()
    for v in state.values():
        total_domains.update(v.get("external_domains", {}).keys())
    errors = sum(1 for v in state.values() if v.get("error"))
    print(f"Total pages collected: {total_pages}")
    print(f"Distinct external domains found: {len(total_domains)}")
    print(f"Locals with errors: {errors}")


if __name__ == "__main__":
    main()
