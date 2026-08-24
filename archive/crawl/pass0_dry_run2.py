import csv
import json

from scrape_lib2 import (
    fc_client, with_retry, credits_remaining, is_scrapeable_url,
    check_dns_and_redirect, domain_of, fingerprint_platform, matches_keywords,
    matches_external_anchor_keywords, unionactive_page_value,
    extract_markdown_links, EXTERNAL_DOMAIN_KEYWORDS,
)

DRY_RUN_LUS = ["134", "1", "3", "613", "98", "46"]


def load_targets():
    with open("out/scrape_targets.csv", encoding="utf-8") as f:
        return {r["lu_number"]: r for r in csv.DictReader(f)}


def normalize_url(u):
    u = u.strip()
    if not u:
        return None
    if not u.lower().startswith("http"):
        u = "http://" + u
    return u


def process_local(lu, t, credits_before_local):
    print(f"\n{'='*70}\nLU {lu}  ({t['charter_city']}, {t['charter_state']})")
    print(f"{'='*70}")
    home_url = normalize_url(t["website"])
    print(f"Directory URL: {home_url}")

    ok, final_url, status, err = check_dns_and_redirect(home_url)
    if not ok:
        print(f"  DNS/redirect check FAILED: {err}  -- suspect URL, would go to /search fallback in the real pipeline")
        return
    if final_url is None:
        print(f"  DNS resolved but HTTP check errored ({err}) -- suspect URL, would go to /search fallback in the real pipeline")
        return
    print(f"  DNS ok, resolved -> {final_url}  (HTTP {status})")

    doc, err = with_retry(fc_client().scrape, final_url, formats=["markdown", "links", "html"], only_main_content=False)
    if err:
        print(f"  HOMEPAGE SCRAPE FAILED: {err}")
        return
    md, links, html = doc.markdown or "", doc.links or [], doc.html or ""
    print(f"  Homepage scraped OK. markdown={len(md)} chars, links={len(links)}, html={len(html)} chars")

    platform = fingerprint_platform(final_url, html, links)
    print(f"  PLATFORM: {platform}")

    home_domain = domain_of(final_url)
    pages_collected = [(final_url, md)]
    external_domains_found = set()
    external_domain_urls = {}
    candidate_pages_scraped = []

    # Scan the homepage's OWN links first, on every platform -- a JATC link is
    # often a direct external href in the nav/footer, not behind an internal
    # page= parameter or a same-domain crawled subpage.
    anchor_map_home = {}
    for text, url in extract_markdown_links(md):
        anchor_map_home.setdefault(url, text)
    for l in links:
        dom = domain_of(l)
        if dom and dom != home_domain:
            anchor_text = anchor_map_home.get(l, "")
            if any(k in dom for k in EXTERNAL_DOMAIN_KEYWORDS) or matches_external_anchor_keywords(anchor_text):
                external_domains_found.add(dom)
                external_domain_urls.setdefault(dom, l)
    if external_domains_found:
        print(f"  External domains found directly on homepage: {sorted(external_domains_found)}")

    if platform == "UnionActive":
        anchor_map = {}
        for text, url in extract_markdown_links(md):
            anchor_map.setdefault(url, text)

        seen_pages = set()
        matches = []
        for url in links:
            pv = unionactive_page_value(url)
            if pv is None:
                continue
            kw = matches_keywords(pv.replace("20", " "))
            anchor_text = anchor_map.get(url, "")
            kw2 = matches_keywords(anchor_text)
            if kw or kw2:
                if url in seen_pages:
                    continue
                seen_pages.add(url)
                matches.append((url, kw or kw2, anchor_text, pv))

        matches = matches[:8]
        print(f"  UnionActive page= keyword matches ({len(matches)}, cap 8):")
        for url, kw, anchor_text, pv in matches:
            print(f"    page={pv!r}  anchor={anchor_text!r}  matched_kw={kw!r}")
            print(f"      {url}")

        for url, kw, anchor_text, pv in matches:
            cdoc, cerr = with_retry(fc_client().scrape, url, formats=["markdown", "links"], only_main_content=False)
            if cerr:
                print(f"    SCRAPE FAILED ({url}): {cerr}")
                continue
            cmd = cdoc.markdown or ""
            clinks = cdoc.links or []
            print(f"    Scraped OK: {url}  markdown={len(cmd)} chars")
            pages_collected.append((url, cmd))
            candidate_pages_scraped.append(url)
            c_anchor_map = {}
            for text, u2 in extract_markdown_links(cmd):
                c_anchor_map.setdefault(u2, text)
            for l in clinks:
                dom2 = domain_of(l)
                if dom2 and dom2 != home_domain:
                    if any(k in dom2 for k in EXTERNAL_DOMAIN_KEYWORDS) or matches_external_anchor_keywords(c_anchor_map.get(l, "")):
                        external_domains_found.add(dom2)
                        external_domain_urls.setdefault(dom2, l)

    else:
        job, err = with_retry(
            fc_client().crawl, final_url,
            limit=25, only_main_content=False, formats=["markdown", "links"],
            allow_external_links=False,
        )
        if err:
            print(f"  CRAWL FAILED: {err}")
        else:
            print(f"  Crawl status={job.status} total={job.total} completed={job.completed} "
                  f"credits_used={job.credits_used} pages_returned={len(job.data)}")
            for d in job.data:
                page_url = d.metadata.url if d.metadata else "?"
                pmd = d.markdown or ""
                plinks = d.links or []
                kw = matches_keywords(pmd) or matches_keywords(page_url)
                flag = f"  [KEYWORD MATCH: {kw}]" if kw else ""
                print(f"    - {page_url}  ({len(pmd)} chars){flag}")
                if page_url != final_url:
                    pages_collected.append((page_url, pmd))
                p_anchor_map = {}
                for text, u2 in extract_markdown_links(pmd):
                    p_anchor_map.setdefault(u2, text)
                for l in plinks:
                    dom = domain_of(l)
                    if dom and dom != home_domain:
                        if any(k in dom for k in EXTERNAL_DOMAIN_KEYWORDS) or matches_external_anchor_keywords(p_anchor_map.get(l, "")):
                            external_domains_found.add(dom)
                            external_domain_urls.setdefault(dom, l)

    print(f"  External JATC-like domains found: {sorted(external_domains_found) if external_domains_found else 'NONE'}")
    print(f"  Total pages collected for this local: {len(pages_collected)}")

    used = credits_remaining()
    print(f"  Credits remaining now: {used}  (spent so far this local: {credits_before_local - used})")

    return {
        "lu": lu, "platform": platform, "home_url": final_url,
        "pages_collected": pages_collected,
        "external_domains": sorted(external_domains_found),
        "external_domain_urls": external_domain_urls,
    }


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")
    targets = load_targets()

    results = []
    for lu in DRY_RUN_LUS:
        t = targets.get(lu)
        if not t:
            print(f"\nLU {lu} not found in scrape_targets.csv -- skipping")
            continue
        credits_before_local = credits_remaining()
        r = process_local(lu, t, credits_before_local)
        if r:
            results.append(r)

    end_credits = credits_remaining()
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for r in results:
        print(f"  LU {r['lu']:6} platform={r['platform']:14} pages={len(r['pages_collected']):3} "
              f"external_domains={r['external_domains']}")
    print(f"\nTotal credits used: {start_credits - end_credits}  (start={start_credits} end={end_credits})")


if __name__ == "__main__":
    main()
