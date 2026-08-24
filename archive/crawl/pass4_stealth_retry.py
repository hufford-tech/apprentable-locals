import json

from scrape_lib2 import fc_client, with_retry, credits_remaining, is_shared_host
from pass3_crawl_jatc import save_page, JATC_STATE_PATH


def main():
    start_credits = credits_remaining()
    print(f"Starting credits: {start_credits}")

    with open(JATC_STATE_PATH, encoding="utf-8") as f:
        jatc_state = json.load(f)

    zero_yield = [(dom, v) for dom, v in jatc_state.items() if not v.get("pages")]
    print(f"Zero-yield domains found: {len(zero_yield)}")

    retried = []
    for dom, v in zero_yield:
        print(f"Retrying {dom} with stealth proxy...")
        job, err = with_retry(
            fc_client().crawl, f"https://{dom}",
            limit=10, only_main_content=False, formats=["markdown", "links"],
            allow_external_links=False, sitemap="skip", proxy="stealth",
        )
        if err or job is None or not job.data:
            print(f"  still zero-yield: {err}")
            jatc_state[dom]["stealth_retry_result"] = "still zero-yield"
            jatc_state[dom]["stealth_retry_error"] = err
        else:
            pages = []
            for d in job.data:
                page_url = d.metadata.url if d.metadata else None
                if not page_url:
                    continue
                save_page(dom, page_url, d.markdown or "")
                pages.append(page_url)
            jatc_state[dom]["pages"] = pages
            jatc_state[dom]["stealth_retry_result"] = f"recovered {len(pages)} pages"
            retried.append(dom)
            print(f"  recovered {len(pages)} pages")

    with open(JATC_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(jatc_state, f, indent=2)

    end_credits = credits_remaining()
    print(f"\nDone. Credits used: {start_credits - end_credits}")
    print(f"Domains recovered via stealth: {len(retried)} of {len(zero_yield)}")


if __name__ == "__main__":
    main()
