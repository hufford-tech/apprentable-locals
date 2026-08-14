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

Round 2 (monitor round 1, tasks 2-3): the whole-document hash (now
last_hash_legacy) measured 24.7% false positives over ten minutes -- almost
all of it HTML attributes (CSRF tokens, __VIEWSTATE, cache-busting query
strings, nonces, data-cfemail, S3 presigned URL params) that no visitor
reads. The primary hash now runs over VISIBLE TEXT ONLY -- see
normalize_visible_text() -- with a short list of content-level redactions
for the few things that still churn in real text (dates, times, long digit
runs, a vendor-specific CAPTCHA). A single differing sweep is still weak
evidence even with a better hash, so a change is CANDIDATE on the first
differing sweep and CONFIRMED only when the next sweep reproduces the same
new hash; only confirmed changes move last_changed / write to
monitor_changes.csv. A candidate that reverts is flapping -- see
monitor_flapping.csv -- and means the normalizer still has a live gap for
that URL, not that the page is actually unstable.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import time
from html.parser import HTMLParser

import requests

STATE_PATH = "out/monitor_state.json"
CHANGES_PATH = "out/monitor_changes.csv"
FAILURES_PATH = "out/monitor_failures.csv"
FLAPPING_PATH = "out/monitor_flapping.csv"

USER_AGENT = "Mozilla/5.0 (compatible; IBEW-apprenticeship-monitor/1.0; +https://github.com/)"
TIMEOUT = 15
MAX_RETRIES = 2
SLEEP_BETWEEN = 1.0
FAILURE_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Legacy whole-document normalizer (round 1). Kept only so last_hash_legacy
# can still be compared against for as long as that's useful; the primary
# hash is normalize_visible_text() below.
_TAG_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def normalize_and_hash(html_text):
    stripped = _TAG_RE.sub(" ", html_text)
    collapsed = _WS_RE.sub(" ", stripped).strip().lower()
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Round 2: visible-text extraction. Attributes (where ~60% of the round-1
# noise categories lived -- tokens, nonces, cache-busting query strings,
# data-cfemail, S3 presigned params, feature-flag IDs) are discarded
# entirely by construction: HTMLParser hands handle_data() only text nodes,
# never attribute values. <script>/<style>/<noscript>/<head>/<title> content
# and HTML comments never reach handle_data() either.
_SKIP_TAGS = {"script", "style", "noscript", "head", "title"}


class _VisibleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.chunks.append(data)


def extract_visible_text(html_text):
    parser = _VisibleTextExtractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        pass  # tolerate malformed markup -- keep whatever text was collected
    return " ".join(parser.chunks)


# Content-level redactions, applied to visible text only (never to markup --
# that's already gone by this point). Each targets a category actually
# observed in out/monitor_noise_audit.csv (round 1, task 1), not a guess.
_MONTH_RE = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
             r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DAY_RE = (r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|"
           r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)")

DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DATE_US_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
DATE_MONTHNAME_RE = re.compile(
    rf"\b{_MONTH_RE}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b", re.IGNORECASE)
DAY_NAME_RE = re.compile(rf"\b{_DAY_RE}\b", re.IGNORECASE)

# Bare four-digit years: real content ("2026 Program", "Class of 2030") must
# survive untouched -- that's the exact signal a status change would show up
# in. Only redact a bare year immediately next to an actual date/timestamp
# word, or immediately before a hit/visit counter word.
_DATE_WORD_YEAR_RE = re.compile(
    r"\b(copyright|©|updated|since|as of|effective|revised|posted|published|"
    r"generated|current)\b\s*:?\s*\d{4}\b", re.IGNORECASE)
_YEAR_BEFORE_COUNTER_RE = re.compile(r"\b\d{4}\b(?=\s*(?:hits?|visits?)\b)", re.IGNORECASE)

# Batcache-style "generated N seconds ago" stamps (LU 223, LU 952).
BATCACHE_RE = re.compile(r"generated\s+\d+\s+seconds?\s+ago", re.IGNORECASE)

# tradeschoolinc's login page renders its CAPTCHA as a plain-text arithmetic
# challenge ("12 + 7 =") with fresh random operands every request (LU 12,
# 131, 159, 567, 573, 606, 915 in the round-1 noise audit). There's no
# generic token/nonce keyword nearby that would let the date/counter rules
# above catch this -- it's ordinary-looking prose with a plus sign -- so it
# needs its own targeted rule. Vendor-specific and known to be narrow: if
# tradeschoolinc changes their captcha markup this rule stops matching and
# needs updating, same as any other vendor-specific pattern would.
CAPTCHA_RE = re.compile(r"\b\d{1,3}\s*\+\s*\d{1,3}\s*=")

# Standalone runs of 5+ digits: hit counters, autoincrement IDs. Four-digit
# numbers (years, "2026 Program") are deliberately left to the date rules
# above rather than this blanket rule, so real 4-digit content survives.
LONG_DIGIT_RUN_RE = re.compile(r"\b\d{5,}\b")


def _redact_contextual_year(text):
    text = _DATE_WORD_YEAR_RE.sub(lambda m: f"{m.group(1)} <year>", text)
    text = _YEAR_BEFORE_COUNTER_RE.sub("<year>", text)
    return text


def normalize_visible_text(html_text):
    text = extract_visible_text(html_text)
    text = DATE_ISO_RE.sub(" <date> ", text)
    text = DATE_US_RE.sub(" <date> ", text)
    text = DATE_MONTHNAME_RE.sub(" <date> ", text)
    text = TIME_RE.sub(" <time> ", text)
    text = DAY_NAME_RE.sub(" <day> ", text)
    text = BATCACHE_RE.sub(" <generated> ", text)
    text = CAPTCHA_RE.sub(" <captcha> ", text)
    text = _redact_contextual_year(text)
    text = LONG_DIGIT_RUN_RE.sub(" <num> ", text)
    return _WS_RE.sub(" ", text).strip().lower()


def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_and_hash_visible(html_text):
    return hash_text(normalize_visible_text(html_text))


# ---------------------------------------------------------------------------


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


def fetch_with_retry(url):
    """Returns (raw_text_or_None, http_status_or_None, error_or_None).

    Returns the raw response text rather than a hash so callers can
    normalize/hash it themselves (the primary visible-text hash, the legacy
    whole-document hash, or a diagnostic like monitor_noise_audit.py).
    """
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
            return resp.text, resp.status_code, None
        except requests.RequestException as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue
            return None, last_status, last_err
    return None, last_status, last_err


def _new_state_record(url):
    return {
        "url": url, "last_hash": None, "last_hash_legacy": None,
        "last_checked": None, "last_changed": None,
        "pending_hash": None, "pending_since": None,
        "consecutive_failures": 0, "last_http_status": None,
    }


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
    flapping = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for i, url in enumerate(urls_to_process):
        text, http_status, err = fetch_with_retry(url)
        new_hash = normalize_and_hash_visible(text) if text is not None else None
        legacy_hash = normalize_and_hash(text) if text is not None else None
        for local_union_id in url_to_locals[url]:
            rec = state.get(local_union_id, _new_state_record(url))
            for key in ("last_hash_legacy", "pending_hash", "pending_since"):
                rec.setdefault(key, None)
            rec["url"] = url
            rec["last_checked"] = now
            rec["last_http_status"] = http_status

            if new_hash is None:
                rec["consecutive_failures"] = rec.get("consecutive_failures", 0) + 1
                if rec["consecutive_failures"] >= FAILURE_THRESHOLD:
                    failures.append((local_union_id, url, rec["consecutive_failures"], err, now))
                state[local_union_id] = rec
                continue

            rec["consecutive_failures"] = 0
            rec["last_hash_legacy"] = legacy_hash
            old_hash = rec.get("last_hash")

            if old_hash is None:
                # First observation of this URL -- establish the baseline,
                # nothing to confirm yet.
                rec["last_hash"] = new_hash
            elif new_hash == old_hash:
                # Matches the confirmed baseline. A pending candidate that
                # reverted to the old hash instead of confirming is flapping.
                if rec.get("pending_hash") and rec["pending_hash"] != old_hash:
                    flapping.append((local_union_id, url, rec["pending_hash"], old_hash, now))
                rec["pending_hash"] = None
                rec["pending_since"] = None
            elif rec.get("pending_hash") == new_hash:
                # Same new hash on consecutive differing sweeps -- confirmed.
                rec["last_changed"] = now
                changes.append((local_union_id, url, old_hash, new_hash, now))
                rec["last_hash"] = new_hash
                rec["pending_hash"] = None
                rec["pending_since"] = None
            else:
                # First differing sweep (or a different candidate than the
                # one still pending) -- candidate only, not yet confirmed.
                if rec.get("pending_hash") and rec["pending_hash"] != new_hash:
                    flapping.append((local_union_id, url, rec["pending_hash"], new_hash, now))
                rec["pending_hash"] = new_hash
                rec["pending_since"] = now

            state[local_union_id] = rec

        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        if i < len(urls_to_process) - 1:
            time.sleep(SLEEP_BETWEEN)

    # Always materialize the audit files.  A clean sweep is still evidence and
    # should not be confused with a monitor that never ran.
    change_header = ["local_union_id", "url", "old_hash", "new_hash", "detected_at"]
    failure_header = ["local_union_id", "url", "consecutive_failures", "last_error", "detected_at"]
    flapping_header = ["local_union_id", "url", "pending_hash", "reverted_to_or_replaced_by", "detected_at"]
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
    if flapping or not os.path.exists(FLAPPING_PATH):
        write_header = not os.path.exists(FLAPPING_PATH)
        with open(FLAPPING_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(flapping_header)
            w.writerows(flapping)

    print(f"Done. Confirmed changes: {len(changes)}  Flapping: {len(flapping)}  "
          f"Failures logged (>={FAILURE_THRESHOLD} consecutive): {len(failures)}")


if __name__ == "__main__":
    main()
