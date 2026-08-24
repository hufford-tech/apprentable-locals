import csv
import json
import os

from scrape_lib2 import (
    fc_client, with_retry, credits_remaining, domain_of,
    check_dns_and_redirect, fingerprint_platform, is_scrapeable_url,
)

TARGETS_PATH = "out/scrape_targets.csv"
OUT_PATH = "out/url_validation.csv"
PLATFORMS_PATH = "out/site_platforms.csv"


def normalize_url(u):
    u = (u or "").strip()
    if not u:
        return None
    if not u.lower().startswith("http"):
        u = "http://" + u
    return u


def load_targets():
    with open(TARGETS_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pick_search_result(search_data, home_domain):
    """Prefer a plausible-looking result: not a directory/social/aggregator site."""
    BAD_HOSTS = ("facebook.com", "linkedin.com", "yelp.com", "indeed.com",
                 "glassdoor.com", "mapquest.com", "yellowpages.com", "bbb.org",
                 "instagram.com", "twitter.com", "x.com", "wikipedia.org")
    if not search_data or not search_data.web:
        return None
    for r in search_data.web:
        dom = domain_of(r.url)
        if dom and not any(b in dom for b in BAD_HOSTS):
            return r.url
    return search_data.web[0].url if search_data.web else None


def process_one(t):
    lu = t["lu_number"]
    directory_url = normalize_url(t["website"])
    result = {
        "lu_number": lu, "directory_url": directory_url,
        "search_url": "", "chosen_url": "", "disagreed": False,
        "platform": "", "link_count": 0, "resolution_method": "",
    }

    ok, final_url, status, err = check_dns_and_redirect(directory_url) if directory_url else (False, None, None, "no url")
    directory_resolves = ok and final_url is not None and (status is None or status < 400)

    if directory_resolves:
        doc, derr = with_retry(fc_client().scrape, final_url, formats=["markdown", "links", "html"], only_main_content=False)
        homepage_ok = doc is not None and len((doc.markdown or "")) >= 500
    else:
        doc, derr = None, err
        homepage_ok = False

    suspect = (not directory_resolves) or (not homepage_ok)

    if not suspect:
        result["chosen_url"] = final_url
        result["resolution_method"] = "directory (redirect-followed)" if final_url != directory_url else "directory (as-is)"
        result["disagreed"] = (domain_of(final_url) != domain_of(directory_url))
    else:
        search_data, serr = with_retry(
            fc_client().search, f"IBEW Local {lu} {t['charter_city']} apprenticeship", limit=5
        )
        search_url = pick_search_result(search_data, domain_of(directory_url) if directory_url else "")
        result["search_url"] = search_url or ""

        if search_url:
            sok, sfinal, sstatus, serr2 = check_dns_and_redirect(search_url)
            if sok and sfinal:
                sdoc, sderr = with_retry(fc_client().scrape, sfinal, formats=["markdown", "links", "html"], only_main_content=False)
                if sdoc is not None and len((sdoc.markdown or "")) >= 500:
                    result["chosen_url"] = sfinal
                    result["resolution_method"] = "search (directory was suspect)"
                    result["disagreed"] = True
                    doc = sdoc
                    final_url = sfinal
        if not result["chosen_url"]:
            # Nothing worked; fall back to whatever we have, flagged.
            result["chosen_url"] = final_url or directory_url or ""
            result["resolution_method"] = "unresolved (directory and search both failed)"
            result["disagreed"] = True

    if doc is not None:
        md, links, html = doc.markdown or "", doc.links or [], doc.html or ""
        result["platform"] = fingerprint_platform(final_url, html, links)
        result["link_count"] = len(links)

    return result


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")
    targets = load_targets()
    print(f"Total locals to validate: {len(targets)}")

    existing = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r["lu_number"]] = r
        print(f"Resuming: {len(existing)} already validated")

    fieldnames = ["lu_number", "directory_url", "search_url", "chosen_url",
                  "disagreed", "platform", "link_count", "resolution_method"]

    results = list(existing.values())
    processed = 0
    for t in targets:
        lu = t["lu_number"]
        if lu in existing:
            continue
        try:
            r = process_one(t)
        except Exception as e:
            r = {"lu_number": lu, "directory_url": t["website"], "search_url": "",
                 "chosen_url": "", "disagreed": True, "platform": "ERROR",
                 "link_count": 0, "resolution_method": f"exception: {e}"}
        results.append(r)
        processed += 1

        if processed % 25 == 0:
            with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(results)
            print(f"  [checkpoint] {processed} processed this run, {len(results)} total, "
                  f"credits remaining: {credits_remaining()}")

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    end_credits = credits_remaining()
    print(f"\nDone. Total validated: {len(results)}  Credits used this run: {start_credits - end_credits}")

    disagreed = [r for r in results if str(r["disagreed"]) == "True"]
    print(f"Disagreement rate: {len(disagreed)}/{len(results)} = {100.0*len(disagreed)/len(results):.1f}%")

    from collections import Counter
    platform_counts = Counter(r["platform"] for r in results)
    print("Platform distribution:")
    for p, n in platform_counts.most_common():
        print(f"  {p}: {n}")


if __name__ == "__main__":
    main()
