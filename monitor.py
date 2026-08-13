"""
Plain-HTTP content-change monitor for application_url pages.

No Firecrawl, no Anthropic. This is the free/unlimited half of the
monitoring design: fetch each application_url with plain `requests`,
normalize the text, hash it, and compare to the stored hash. Firecrawl
is only triggered manually, by a human, after reviewing out/monitor_changes.csv.

State is keyed by local_union_id (the real primary key -- see build_shippable.py
task 6), not lu_number, because multiple locals can in principle share one
application_url (e.g. a shared regional JATC) and lu_number is only unique
incidentally within the current 242-row extraction, not globally guaranteed.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import time

import requests

STATE_PATH = "out/monitor_state.json"
CHANGES_PATH = "out/monitor_changes.csv"
FAILURES_PATH = "out/monitor_failures.csv"

USER_AGENT = "Mozilla/5.0 (compatible; IBEW-apprenticeship-monitor/1.0; +https://github.com/)"
TIMEOUT = 15
MAX_RETRIES = 2
SLEEP_BETWEEN = 1.0
FAILURE_THRESHOLD = 3

_TAG_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def load_url_to_locals():
    """Returns dict: application_url -> list of local_union_id, using
    targets_with_population.csv as the lu_number -> local_union_id crosswalk."""
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        crosswalk = {r["lu_number"]: r["local_union_id"] for r in csv.DictReader(f)}

    url_to_locals = {}
    with open("out/extraction_v2.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            url = (r.get("application_url") or "").strip()
            if not url:
                continue
            lu = r["lu_number"]
            local_union_id = crosswalk.get(lu)
            if local_union_id is None:
                raise AssertionError(f"lu_number {lu} has no local_union_id in targets_with_population.csv")
            url_to_locals.setdefault(url, []).append(local_union_id)
    return url_to_locals


def normalize_and_hash(html_text):
    stripped = _TAG_RE.sub(" ", html_text)
    collapsed = _WS_RE.sub(" ", stripped).strip().lower()
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def fetch_with_retry(url):
    """Returns (hash_or_None, http_status_or_None, error_or_None)."""
    headers = {"User-Agent": USER_AGENT}
    backoff = 2.0
    last_err = None
    last_status = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT)
            last_status = resp.status_code
            if resp.status_code >= 400:
                last_err = f"HTTP {resp.status_code}"
                if attempt < MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return None, last_status, last_err
            return normalize_and_hash(resp.text), resp.status_code, None
        except requests.RequestException as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue
            return None, last_status, last_err
    return None, last_status, last_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only process the first N distinct URLs")
    ap.add_argument("--resume", action="store_true", help="resume an interrupted run using the latest last_checked marker")
    ap.add_argument("--dry-run", action="store_true", help="build the URL list and print counts, make no HTTP requests")
    args = ap.parse_args()

    url_to_locals = load_url_to_locals()
    distinct_urls = list(url_to_locals.keys())
    print(f"Distinct application_url values (non-empty): {len(distinct_urls)}")

    if args.dry_run:
        print("--dry-run: no HTTP requests made.")
        return

    urls_to_process = distinct_urls if args.limit is None else distinct_urls[:args.limit]
    print(f"Processing {len(urls_to_process)} URL(s) this run "
          f"({'all' if args.limit is None else f'limit={args.limit}'})")

    state = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)

    resume_cutoff = None
    if args.resume and state:
        checked = [r.get("last_checked") for r in state.values() if r.get("last_checked")]
        resume_cutoff = max(checked) if checked else None
        if resume_cutoff:
            distinct_urls = [
                url for url in distinct_urls
                if not all(state.get(local_id, {}).get("last_checked") == resume_cutoff
                           for local_id in url_to_locals[url])
            ]
            print(f"--resume: skipping URL groups completed at {resume_cutoff}; remaining {len(distinct_urls)}")

    changes = []
    failures = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for i, url in enumerate(urls_to_process):
        new_hash, http_status, err = fetch_with_retry(url)
        for local_union_id in url_to_locals[url]:
            rec = state.get(local_union_id, {
                "url": url, "last_hash": None, "last_checked": None,
                "last_changed": None, "consecutive_failures": 0, "last_http_status": None,
            })
            rec["url"] = url
            rec["last_checked"] = now
            rec["last_http_status"] = http_status

            if new_hash is None:
                rec["consecutive_failures"] = rec.get("consecutive_failures", 0) + 1
                if rec["consecutive_failures"] >= FAILURE_THRESHOLD:
                    failures.append((local_union_id, url, rec["consecutive_failures"], err, now))
            else:
                rec["consecutive_failures"] = 0
                old_hash = rec.get("last_hash")
                if old_hash is not None and old_hash != new_hash:
                    rec["last_changed"] = now
                    changes.append((local_union_id, url, old_hash, new_hash, now))
                rec["last_hash"] = new_hash

            state[local_union_id] = rec

        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        if i < len(urls_to_process) - 1:
            time.sleep(SLEEP_BETWEEN)

    # Always materialize the audit files.  A clean sweep is still evidence and
    # should not be confused with a monitor that never ran.
    change_header = ["local_union_id", "url", "old_hash", "new_hash", "detected_at"]
    failure_header = ["local_union_id", "url", "consecutive_failures", "last_error", "detected_at"]
    if changes or not os.path.exists(CHANGES_PATH):
        write_header = not os.path.exists(CHANGES_PATH)
        with open(CHANGES_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(change_header)
            w.writerows(changes)
    if failures or not os.path.exists(FAILURES_PATH):
        write_header = not os.path.exists(FAILURES_PATH)
        with open(FAILURES_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(failure_header)
            w.writerows(failures)

    print(f"Done. Changes detected: {len(changes)}  Failures logged (>={FAILURE_THRESHOLD} consecutive): {len(failures)}")


if __name__ == "__main__":
    main()
