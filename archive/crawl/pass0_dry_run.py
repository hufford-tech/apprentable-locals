import json

import csv

from scrape_lib import (
    load_targets, normalize_url, scrape_one, discover_candidates,
    call_extraction, credits_remaining,
)

DRY_RUN_LUS = ["134", "1", "1245", "3", "613"]


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")

    targets = {t["lu_number"]: t for t in load_targets()}

    # LU 1245 carries no trade class 'i' (it's catv/em/govt/lctt/o/t/u -- Outside/utility),
    # so it's correctly absent from scrape_targets.csv. Pulled in here from the full
    # locals table for dry-run purposes only, per the user's explicit LU list.
    if "1245" not in targets:
        with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
            r = next(r for r in csv.DictReader(f) if r["lu_number"] == "1245")
        targets["1245"] = {
            "lu_number": "1245", "website": r["website"],
            "charter_city": r["charter_city"], "charter_state": r["charter_state"],
        }
        print("NOTE: LU 1245 is not in scrape_targets.csv (no trade class 'i' -- "
              "it's Outside/utility). Included here anyway per the explicit dry-run "
              "list; it will NOT be part of the real 245-local Pass 1-4 run.")

    scrapes_done = 0

    for lu in DRY_RUN_LUS:
        t = targets.get(lu)
        print(f"\n{'='*70}\nLU {lu}  ({t['charter_city']}, {t['charter_state']})")
        print(f"{'='*70}")
        home_url = normalize_url(t["website"])
        print(f"Homepage URL: {home_url}")

        doc, err = scrape_one(home_url)
        scrapes_done += 1
        if err:
            print(f"  SCRAPE FAILED: {err}")
            continue

        md = doc.markdown or ""
        links = doc.links or []
        print(f"  Scraped OK. markdown length={len(md)}  links found={len(links)}")

        candidates = discover_candidates(home_url, links, md, cap=4)
        print(f"  Candidates discovered ({len(candidates)}):")
        for c in candidates:
            print(f"    rank={c['rank']} external={c['is_external']} reason={c['match_reason']}")
            print(f"      {c['candidate_url']}")

        pages = [(home_url, md)]
        for c in candidates:
            cdoc, cerr = scrape_one(c["candidate_url"])
            scrapes_done += 1
            if cerr:
                print(f"  CANDIDATE SCRAPE FAILED ({c['candidate_url']}): {cerr}")
                continue
            cmd = cdoc.markdown or ""
            print(f"  Scraped candidate OK: {c['candidate_url']}  markdown length={len(cmd)}")
            pages.append((c["candidate_url"], cmd))

        print(f"\n  Running extraction over {len(pages)} page(s)...")
        try:
            extracted, usage = call_extraction(lu, t["charter_city"], pages)
        except Exception as e:
            print(f"  EXTRACTION FAILED: {e}")
            continue

        print(f"  Extraction token usage: {usage}")
        print("  Extracted JSON:")
        print(json.dumps(extracted, indent=2))

        current_credits = credits_remaining()
        used_so_far = start_credits - current_credits
        print(f"\n  Cumulative credits used so far: {used_so_far}  (scrapes issued: {scrapes_done})")

    end_credits = credits_remaining()
    print(f"\n{'='*70}")
    print(f"DRY RUN COMPLETE. Total scrapes issued: {scrapes_done}")
    print(f"Credits at start: {start_credits}  Credits at end: {end_credits}  Used: {start_credits - end_credits}")
    projected_full = (start_credits - end_credits) / scrapes_done * 245 * (scrapes_done / len(DRY_RUN_LUS)) if scrapes_done else 0
    print(f"Rough per-local average scrapes: {scrapes_done / len(DRY_RUN_LUS):.1f}")


if __name__ == "__main__":
    main()
