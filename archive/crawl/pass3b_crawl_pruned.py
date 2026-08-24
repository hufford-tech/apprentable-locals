import csv
import json
import os

from scrape_lib2 import fc_client, with_retry, credits_remaining, is_shared_host
from pass3_crawl_jatc import save_page, JATC_STATE_PATH, LOCAL_TO_JATC_PATH

DROP_EXACT = {
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "facebook.com",
    "electricaltrainingalliance.org", "ibew.org", "necanet.org", "aflcio.org",
    "tiktok.com", "bing.com", "legacy.com", "jacobinmag.com", "canva.com",
    "issuu.com", "sites.google.com", "drive.google.com", "dropbox.com",
    "mailchi.mp", "linktr.ee", "bit.ly", "cutt.ly",
    "oshatraining.com", "360training.com",
}
DROP_SUFFIX = (".electricaltrainingalliance.org", ".wordpress.com")
STATE_AGENCY_MARKERS = (".gov",)
CRAWL_LIMIT = 8
HALT_AT_CREDITS = 400


def population(lu, pop):
    v = pop.get(lu, {}).get("population_current_served_inside", "")
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def build_pruned_ordered_queue():
    with open("out/local_crawl_state.json", encoding="utf-8") as f:
        local_state = json.load(f)
    with open("out/extraction_pass2only.csv", encoding="utf-8") as f:
        extraction = {r["lu_number"]: r for r in csv.DictReader(f)}
    with open("out/scrape_targets.csv", encoding="utf-8") as f:
        target_lus = [r["lu_number"] for r in csv.DictReader(f)]
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        pop = {r["lu_number"]: r for r in csv.DictReader(f)}

    complete, partial, empty = [], [], []
    for lu in target_lus:
        r = extraction.get(lu)
        if r is None:
            empty.append(lu)
            continue
        has_url = bool((r.get("application_url") or "").strip())
        has_status = r.get("accepting_applications", "unknown") not in ("unknown", "", None)
        if has_url and has_status:
            complete.append(lu)
        elif has_url or has_status:
            partial.append(lu)
        else:
            empty.append(lu)

    needy = set(partial) | set(empty)

    domain_max_pop = {}
    domain_locals = {}
    for lu in needy:
        doms = local_state.get(lu, {}).get("external_domains", {})
        p = population(lu, pop)
        for dom, url in doms.items():
            domain_locals.setdefault(dom, []).append(lu)
            domain_max_pop[dom] = max(domain_max_pop.get(dom, 0), p)

    domain_example_url = {}
    for lu in needy:
        for dom, url in local_state.get(lu, {}).get("external_domains", {}).items():
            domain_example_url.setdefault(dom, url)

    kept, state_agency = [], []
    for d in domain_max_pop:
        if d in DROP_EXACT or any(d.endswith(suf) for suf in DROP_SUFFIX):
            continue
        elif any(m in d for m in STATE_AGENCY_MARKERS):
            state_agency.append(d)
        else:
            kept.append(d)

    all_queue = kept + state_agency
    all_queue.sort(key=lambda d: domain_max_pop[d], reverse=True)

    source_type = {d: ("state_agency" if d in state_agency else "jatc") for d in all_queue}
    return all_queue, domain_example_url, domain_locals, source_type


def main():
    queue, example_url, domain_locals, source_type = build_pruned_ordered_queue()
    print(f"Pruned, population-ordered queue: {len(queue)} domains "
          f"({sum(1 for d in queue if source_type[d]=='state_agency')} state_agency, "
          f"{sum(1 for d in queue if source_type[d]=='jatc')} jatc)")

    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")

    jatc_state = {}
    if os.path.exists(JATC_STATE_PATH):
        with open(JATC_STATE_PATH, encoding="utf-8") as f:
            jatc_state = json.load(f)
        print(f"Resuming: {len(jatc_state)} domains already in state")

    processed = 0
    halted_early = False
    for dom in queue:
        if dom in jatc_state:
            continue

        cur_credits = credits_remaining()
        if cur_credits <= HALT_AT_CREDITS:
            print(f"HALT: credits_remaining={cur_credits} <= {HALT_AT_CREDITS} threshold. "
                  f"Stopped before processing domain '{dom}'.")
            halted_early = True
            break

        ex_url = example_url.get(dom, f"https://{dom}")
        if is_shared_host(dom):
            doc, err = with_retry(fc_client().scrape, ex_url, formats=["markdown", "links"], only_main_content=False)
            if err or doc is None:
                jatc_state[dom] = {"pages": [], "error": err, "shared_host": True, "source_type": source_type[dom]}
            else:
                save_page(dom, ex_url, doc.markdown or "")
                jatc_state[dom] = {"pages": [ex_url], "error": None, "shared_host": True, "source_type": source_type[dom]}
        else:
            job, err = with_retry(
                fc_client().crawl, ex_url,
                limit=CRAWL_LIMIT, only_main_content=False, formats=["markdown", "links"],
                allow_external_links=False, sitemap="skip",
            )
            if err or job is None or not job.data:
                jatc_state[dom] = {"pages": [], "error": err, "shared_host": False, "source_type": source_type[dom]}
            else:
                pages = []
                for d in job.data:
                    page_url = d.metadata.url if d.metadata else None
                    if not page_url:
                        continue
                    save_page(dom, page_url, d.markdown or "")
                    pages.append(page_url)
                jatc_state[dom] = {"pages": pages, "error": None, "shared_host": False, "source_type": source_type[dom]}

        processed += 1
        if processed % 10 == 0:
            with open(JATC_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(jatc_state, f, indent=2)
            print(f"  [checkpoint] {processed} processed this run, credits remaining: {credits_remaining()}")

    with open(JATC_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(jatc_state, f, indent=2)

    with open(LOCAL_TO_JATC_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lu_number", "jatc_domain", "page_count", "source_type"])
        for dom, lus in domain_locals.items():
            page_count = len(jatc_state.get(dom, {}).get("pages", []))
            st = jatc_state.get(dom, {}).get("source_type", "jatc")
            for lu in lus:
                w.writerow([lu, dom, page_count, st])

    end_credits = credits_remaining()
    zero_yield = [d for d in queue if d in jatc_state and not jatc_state[d].get("pages")]
    print(f"\nDone. Processed this run: {processed}  Credits used this run: {start_credits - end_credits}")
    print(f"Credits remaining: {end_credits}")
    print(f"Halted early: {halted_early}")
    print(f"Zero-yield domains: {len(zero_yield)}")
    for d in zero_yield:
        print(f"  {d}: {jatc_state[d].get('error')}")


if __name__ == "__main__":
    main()
