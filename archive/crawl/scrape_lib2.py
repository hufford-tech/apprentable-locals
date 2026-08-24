import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
load_dotenv()

from firecrawl import Firecrawl

_FC = None

# ---- rate limiting: 10 req/min cap, exponential backoff on 429 ----
_REQUEST_TIMES = []
_MAX_PER_MIN = 10
_REQUEST_COUNT = 0
_LAST_PROGRESS_PRINT = 0


def fc_client():
    global _FC
    if _FC is None:
        _FC = Firecrawl()
    return _FC


def _throttle():
    global _REQUEST_TIMES
    now = time.time()
    _REQUEST_TIMES = [t for t in _REQUEST_TIMES if now - t < 60]
    if len(_REQUEST_TIMES) >= _MAX_PER_MIN:
        sleep_for = 60 - (now - _REQUEST_TIMES[0]) + 0.5
        if sleep_for > 0:
            time.sleep(sleep_for)
    _REQUEST_TIMES.append(time.time())


def credits_remaining():
    return fc_client().get_credit_usage().remaining_credits


_TIMEOUT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fc-call")


def with_retry(fn, *args, max_retries=6, call_timeout=180, **kwargs):
    """Call a Firecrawl SDK method with rate-limit-aware retry.
    429s are not billed, so retry with exponential backoff rather than skip.
    call_timeout bounds each individual attempt (e.g. a stuck blocking crawl poll)
    so a single hung call can never stall the whole pipeline; a timed-out attempt
    is treated as a normal failure (returned as an error), not retried."""
    global _REQUEST_COUNT
    backoff = 2.0
    for attempt in range(max_retries):
        _throttle()
        future = _TIMEOUT_EXECUTOR.submit(fn, *args, **kwargs)
        try:
            result = future.result(timeout=call_timeout)
            _REQUEST_COUNT += 1
            maybe_print_progress()
            return result, None
        except FutureTimeoutError:
            _REQUEST_COUNT += 1
            maybe_print_progress()
            return None, f"timed out after {call_timeout}s (call abandoned, pipeline continuing)"
        except Exception as e:
            msg = str(e)
            if "Rate Limit" in msg or "429" in msg:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            _REQUEST_COUNT += 1
            maybe_print_progress()
            return None, msg
    return None, f"Exceeded max retries ({max_retries}) due to rate limiting"


def maybe_print_progress(interval=25):
    global _LAST_PROGRESS_PRINT
    if _REQUEST_COUNT - _LAST_PROGRESS_PRINT >= interval:
        _LAST_PROGRESS_PRINT = _REQUEST_COUNT
        try:
            remaining = credits_remaining()
            print(f"  [progress] {_REQUEST_COUNT} requests issued, {remaining} credits remaining")
        except Exception:
            print(f"  [progress] {_REQUEST_COUNT} requests issued")


# ---- URL sanity checks (no Firecrawl credits) ----
BAD_SCHEMES = ("mailto:", "tel:", "javascript:", "#")


def is_scrapeable_url(url):
    if not url:
        return False
    u = url.strip()
    if u.startswith(BAD_SCHEMES) or u == "" or u.startswith("#"):
        return False
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    return True


def check_dns_and_redirect(url, timeout=20):
    """Return (resolves: bool, final_url: str|None, status: int|None, error: str|None).
    Plain HTTP check -- no Firecrawl credits spent."""
    try:
        host = urlparse(url).hostname
        socket.gethostbyname(host)
    except Exception as e:
        return False, None, None, f"DNS failure: {e}"

    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout,
                              headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code >= 400 or resp.status_code == 405:
            resp = requests.get(url, allow_redirects=True, timeout=timeout,
                                 headers={"User-Agent": "Mozilla/5.0"})
        return True, resp.url, resp.status_code, None
    except requests.RequestException as e:
        return True, None, None, f"HTTP error: {e}"


def domain_of(url):
    try:
        d = urlparse(url).netloc.lower()
        if d.startswith("www."):
            d = d[4:]
        return d
    except Exception:
        return ""


# ---- CMS fingerprinting ----
def fingerprint_platform(url, html, links):
    html_l = (html or "").lower()
    link_blob = " ".join(links or []).lower()

    if "unionactive" in html_l or "zone=/unionactive/" in link_blob:
        return "UnionActive"
    if "wp-content" in html_l or "wp-json" in html_l or "wp-includes" in html_l or "wp-content" in link_blob:
        return "WordPress"
    if "wixstatic.com" in html_l or "wix.com" in html_l or "_wixcss" in html_l:
        return "Wix"
    if "squarespace.com" in html_l or "static1.squarespace.com" in html_l or "squarespace-cdn" in html_l:
        return "Squarespace"
    if "weebly.com" in html_l or "weeblycloud.com" in html_l:
        return "Weebly"
    return "other/custom"


KEYWORDS = [
    "apprentic", "training", "jatc", "etp", "apply", "application",
    "become", "recruit", "aptitude", "wireman", "education", "career",
    "jib", "joint industry", "joint apprentice", "jac", "jeatc", "eatc",
    "ejatc", "njatc", "technical institute", "training alliance",
    "training center", "training trust", "electrical training",
    "institute", "academy", "recruitment", "eligibility",
    "how to apply", "join",
]

EXTERNAL_DOMAIN_KEYWORDS = ["jatc", "jac", "training", "institute", "jib"]

# Stricter subset for promoting a domain to "external JATC candidate" based on
# anchor text alone (the full KEYWORDS list is too generic for this -- "become",
# "join", "career", "education" alone shouldn't flag e.g. flickr.com or aflcio.org
# just because a nearby link's URL happens to contain one of those words).
EXTERNAL_ANCHOR_KEYWORDS = [
    "apprentic", "jatc", "jib", "joint industry", "joint apprentice", "jac",
    "jeatc", "eatc", "ejatc", "njatc", "technical institute",
    "training alliance", "training center", "training trust",
    "electrical training", "aptitude test", "how to apply",
]


def decode_query_value(v):
    from urllib.parse import unquote_plus
    v = unquote_plus(v or "")
    v = v.replace("20", " ") if re.fullmatch(r"[A-Za-z0-9 ]*(20[A-Za-z0-9]*)+", v) else v
    return v.lower()


def unionactive_page_value(url):
    from urllib.parse import urlparse, parse_qs
    try:
        q = parse_qs(urlparse(url).query)
        if "page" in q:
            return q["page"][0]
    except Exception:
        pass
    return None


def matches_keywords(text):
    text_l = (text or "").lower()
    for kw in KEYWORDS:
        if kw in text_l:
            return kw
    return None


def matches_external_anchor_keywords(text):
    text_l = (text or "").lower()
    for kw in EXTERNAL_ANCHOR_KEYWORDS:
        if kw in text_l:
            return kw
    return None


def extract_markdown_links(markdown_text):
    if not markdown_text:
        return []
    pattern = re.compile(r"\[([^\]]*)\]\((https?://[^\s)]+)\)")
    return [(text.strip(), url.strip()) for text, url in pattern.findall(markdown_text)]


# ---- Shared-host guard ----
SHARED_HOSTS = [
    "sites.google.com", "wordpress.com", "issuu.com", "vimeo.com",
    "youtube.com", "facebook.com", "drive.google.com", "dropbox.com",
    "mailchi.mp", "linktr.ee",
]


def is_shared_host(domain):
    domain = (domain or "").lower()
    for h in SHARED_HOSTS:
        if domain == h or domain.endswith("." + h):
            return True
    return False


# ---- Extraction (Pass 5) ----
def anthropic_client():
    import anthropic
    return anthropic.Anthropic()


EXTRACTION_SYSTEM_PROMPT = """You extract IBEW apprenticeship program OBSERVATIONS from scraped web page markdown for a single local union (LU).

You are an observer, not a judge. You NEVER decide whether applications are "currently open." That determination is made later, deterministically, in code, by comparing the dated facts you extract against today's date. Your only job is to record every date-bearing or status-bearing statement you find, verbatim-grounded, as a structured observation.

Rules, follow exactly:
- Never infer or guess. If a fact is absent from the page text, leave its field empty/null and lower confidence accordingly.
- Do NOT output any judgment like "currently accepting" or "yes/no" -- there is no such field in the schema. Only record what the page states and when it says that was true.
- jatc_domain must be the domain of one of the SOURCE URLs given to you below. Never state a domain, subdomain, or organization name that does not literally appear in the provided source URLs or page text.
- If the page content appears to describe a different IBEW local than the expected LU number, set confidence to "low" and note the mismatch in other_requirements -- do not silently substitute.
- source_url (top-level, per-window, and per-status_statement) must be one of the URLs provided to you for this local.
- application_method should reflect how applications are actually submitted, "unknown" if not stated.
- website_corrected/original_website are supplied to you as known facts (not something to infer) -- copy them through as given.
- A "CANDIDATE EVIDENCE" section may appear at the top of the pages, listing keyword-matched excerpts to help you find relevant passages fast. These are a finding aid ONLY -- some will be false positives from unrelated boilerplate (e.g. "always" in a member testimonial). Verify every candidate against the full page text below it before using it. Do not extract anything from the candidate list that isn't also present, in context, in the full page text.

WINDOWS ARRAY -- read carefully, this is the part most often done wrong:
- Produce one array element per DISTINCT intake period described on the pages. A JATC that runs multiple intakes per year (e.g. "weeks of March, June, and September") gets one element per named period, not one merged element.
- precision="absolute": the page states a full date INCLUDING a 4-digit year for open and/or close. Fill open_date/close_date as ISO (YYYY-MM-DD).
- precision="recurring": the page states a month and day (or month alone, or a named period like "first two weeks of March") WITHOUT a year, and the timing is specific enough to name month/day. Fill open_month/open_day/close_month/close_day (integers) wherever the text specifies them -- do NOT leave these blank just because there's no year. Leave open_date/close_date empty. Do NOT infer a year. Do NOT infer a day-of-month that isn't stated.
- precision="relative": the timing is described relative to some event or in vague terms that don't resolve to any specific month/day at all (e.g. "when the list reaches 500 names"). Put the verbatim phrase in relative_description; leave month/day/date fields empty.
- precision="none": a status is stated but the window carries no timing information whatsoever (this is rare for windows -- most no-date status claims belong in status_statements instead, see below).
- is_recurring_annual: true only if the page explicitly frames the window as annual/yearly/"every August"/etc.
- Never infer a year under any circumstance -- not from today's date, not from the page's apparent age, not from surrounding context. Never infer a day from a month alone, or a month from a day alone.
- evidence_quote (per window) must be copied verbatim from the source text, under 15 words.

STATUS_STATEMENTS ARRAY -- this replaces any yes/no judgment:
- One array element per distinct sentence/claim about application status found on the pages.
- verbatim_text: copied exactly from the source, under 25 words.
- statement_type:
    "rolling"   -- the text describes ongoing/year-round/continuous/anytime intake (e.g. "we accept applications year-round", "walk-ins welcome any time", "rolling enrollment").
    "open"      -- the text states applications are currently open/being accepted, without necessarily giving a specific window (if it also gives a dated window, ALSO add that window to the windows array).
    "closed"    -- the text states applications are currently closed/not being accepted.
    "reopening" -- the text states a specific date when applications will (re)open, phrased as an announcement rather than a defined window (e.g. "we will reopen November 2nd, 2026"). Put that date in stated_effective_date as ISO, ONLY if a full year is given.
    "unknown"   -- some status-adjacent language exists but doesn't clearly resolve to one of the above.
- stated_effective_date: ISO date, ONLY if the statement itself names a specific date (the reopening date for "reopening", or an explicit "as of <date>" for others). Null otherwise. Never infer a year.
- source_url: the page this statement came from.

LOCAL-LEVEL DATE FIELDS:
- page_last_updated: ISO date, ONLY if a page explicitly states when it was last updated/modified/posted (e.g. a "last updated" footer, a dated news post that IS the apprenticeship page). Null otherwise.
- content_year: the single latest 4-digit year mentioned ANYWHERE in the scraped text for this local (windows, news posts, copyright footers, event dates) -- scan broadly. Null if no year appears anywhere.
- is_stale: true if content_year is earlier than the current year. You will be told the current year in the prompt.

EXAMPLES -- study these four carefully, they cover the cases most often gotten wrong:

Example 1 -- ROLLING / YEAR-ROUND INTAKE:
  Source text: "We accept applications year-round. Stop by our office any time during business hours to pick up an application packet."
  Correct extraction: windows=[]. status_statements=[{"verbatim_text":"We accept applications year-round","statement_type":"rolling","stated_effective_date":null,"source_url":"<the page url>"}]
  Why: this is a genuine, explicit statement about ongoing status. Do not leave status_statements empty just because there's no calendar date -- "rolling" is exactly the type for this.

Example 2 -- DATED WINDOW WITH YEAR:
  Source text: "The 2026 apprenticeship application period opens March 3, 2026 and closes March 14, 2026."
  Correct extraction: windows=[{"precision":"absolute","open_date":"2026-03-03","close_date":"2026-03-14","open_month":null,"open_day":null,"close_month":null,"close_day":null,"is_recurring_annual":false,"relative_description":"","time_of_day":"","method":"unknown","cap":"","evidence_quote":"opens March 3, 2026 and closes March 14, 2026","source_url":"<the page url>"}]. status_statements=[] (the window itself carries the information; no separate status sentence to record here).

Example 3 -- MONTH/DAY WINDOW WITHOUT A YEAR:
  Source text: "Applications are accepted the first two weeks of September each year."
  Correct extraction: windows=[{"precision":"recurring","open_date":"","close_date":"","open_month":9,"open_day":null,"close_month":9,"close_day":null,"is_recurring_annual":true,"relative_description":"first two weeks of September","time_of_day":"","method":"unknown","cap":"","evidence_quote":"first two weeks of September each year","source_url":"<the page url>"}]
  Why: month is known (9), no year is given so open_date/close_date stay empty, no specific day is named so open_day/close_day stay null, and "each year" makes is_recurring_annual=true.

Example 4 -- GENUINE ABSENCE:
  Source text: pages describe the union's history, benefits, dues, and officers, with no sentence anywhere about applying, apprenticeship intake, or program status.
  Correct extraction: windows=[]. status_statements=[]. has_apprenticeship may still be true if a program is named, but no status/timing claim exists to extract.

Output ONLY a single JSON object matching the exact schema given in the user message. No prose, no markdown fences, no commentary.
"""


WINDOW_SCHEMA = {
    "precision": "absolute | recurring | relative | none",
    "open_date": "ISO date or empty (absolute only)",
    "close_date": "ISO date or empty (absolute only)",
    "open_month": "int 1-12 or null",
    "open_day": "int 1-31 or null",
    "close_month": "int 1-12 or null",
    "close_day": "int 1-31 or null",
    "is_recurring_annual": "bool",
    "relative_description": "verbatim phrase or empty",
    "time_of_day": "string or empty",
    "method": "online | mail | email | in_person | phone | unknown",
    "cap": "string, e.g. 'first 2000 registered letters', empty if none",
    "evidence_quote": "verbatim, under 15 words",
    "source_url": "string, one of the page URLs below",
}

STATUS_STATEMENT_SCHEMA = {
    "verbatim_text": "copied exactly from source, under 25 words",
    "statement_type": "rolling | open | closed | reopening | unknown",
    "stated_effective_date": "ISO date or null",
    "source_url": "string, one of the page URLs below",
}

EXTRACTION_SCHEMA = {
    "has_apprenticeship": "bool",
    "program_name": "string",
    "jatc_name": "string",
    "jatc_domain": "string",
    "application_url": "string",
    "windows": [WINDOW_SCHEMA],
    "status_statements": [STATUS_STATEMENT_SCHEMA],
    "occupations": ["array of strings"],
    "min_age": "int or null",
    "min_education": "string",
    "citizenship_required": "bool",
    "aptitude_test": "string",
    "interview_required": "bool",
    "math_requirement": "string",
    "other_requirements": ["array of strings"],
    "contact_email": "string",
    "contact_phone": "string",
    "application_method": "online | mail | email | in_person | phone | unknown",
    "has_notification_list": "bool",
    "notification_instructions": "string",
    "state_dol_url": "string, pass through the supplied fact or empty",
    "website_corrected": "bool, pass through the supplied fact",
    "original_website": "string, pass through the supplied fact",
    "page_last_updated": "ISO date or null",
    "content_year": "int or null",
    "is_stale": "bool",
    "confidence": "high | medium | low",
}


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def build_highlighted_excerpts(pages, keywords=None, cap=40):
    """Scan all pages for keyword hits and pull each match's sentence plus one
    sentence of context on either side. Deduped, capped. Returns a list of
    (url, excerpt) tuples -- a finding aid, not a replacement for full pages."""
    if keywords is None:
        keywords = PREFILTER_KEYWORDS
    seen = set()
    excerpts = []
    for url, md in pages:
        if not md:
            continue
        sentences = _SENTENCE_SPLIT_RE.split(md.replace("\n", " "))
        for i, sent in enumerate(sentences):
            low = sent.lower()
            if any(k in low for k in keywords):
                start = max(0, i - 1)
                end = min(len(sentences), i + 2)
                excerpt = " ".join(sentences[start:end]).strip()
                excerpt = re.sub(r"\s+", " ", excerpt)[:400]
                key = (url, excerpt)
                if key in seen or not excerpt:
                    continue
                seen.add(key)
                excerpts.append((url, excerpt))
                if len(excerpts) >= cap:
                    return excerpts
    return excerpts


def build_extraction_user_prompt(lu_number, expected_city, pages, current_year,
                                  website_corrected=False, original_website="", state_dol_url=""):
    parts = [
        f"Expected local union number: LU {lu_number} ({expected_city}).",
        f"Current year (for is_stale comparison ONLY -- never use this to fill in a missing year on a date): {current_year}",
        f"website_corrected fact: {website_corrected}",
        f"original_website fact: {original_website}",
        f"state_dol_url fact (if known): {state_dol_url}",
        "Below are one or more scraped pages (homepage, crawled subpages, and JATC/training-partner pages) for this local.",
        "Extract into exactly this JSON schema (all keys required, use null/empty string/empty array/\"unknown\" where a fact is absent):",
        json.dumps(EXTRACTION_SCHEMA, indent=2),
        "",
    ]

    excerpts = build_highlighted_excerpts(pages)
    if excerpts:
        parts.append(
            "CANDIDATE EVIDENCE (found by keyword scan, verify each against full text below; "
            "these may be false positives from unrelated boilerplate):"
        )
        for url, excerpt in excerpts:
            parts.append(f"  [{url}] ...{excerpt}...")
        parts.append("")

    parts.append("PAGES:")
    for url, md in pages:
        parts.append(f"\n=== SOURCE URL: {url} ===\n{md[:15000]}")
    return "\n".join(parts)


_EXTRACTION_SYSTEM_BLOCKS = [
    {"type": "text", "text": EXTRACTION_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
]


class ExtractionIncompleteError(Exception):
    """Raised when the model's response was truncated (stop_reason != end_turn)
    rather than completing normally -- treated as a hard failure, never parsed."""


def call_extraction(lu_number, expected_city, pages, model="claude-sonnet-4-6", current_year=None, **kwargs):
    import datetime
    if current_year is None:
        current_year = datetime.date.today().year
    client = anthropic_client()
    user_prompt = build_extraction_user_prompt(lu_number, expected_city, pages, current_year, **kwargs)
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=_EXTRACTION_SYSTEM_BLOCKS,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if resp.stop_reason != "end_turn":
        raise ExtractionIncompleteError(
            f"LU {lu_number}: stop_reason={resp.stop_reason!r} (response truncated, not parsed)"
        )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return json.loads(text), resp.usage


PREFILTER_KEYWORDS = [
    "apprentic", "application", "apply", "jatc", "training", "aptitude",
    "wireman", "eligibility", "requirement", "recruit", "intake", "enroll",
]


def prefilter_pages(pages):
    """Keep only pages whose text mentions an apprenticeship-relevant keyword;
    fall back to the first page (homepage) alone if that leaves nothing."""
    kept = [(u, md) for u, md in pages if any(k in (md or "").lower() for k in PREFILTER_KEYWORDS)]
    if not kept:
        return pages[:1]
    return kept


def build_extraction_batch_request(custom_id, lu_number, expected_city, pages, current_year,
                                    model="claude-sonnet-4-6", **kwargs):
    """Build one Anthropic Message Batches API request dict, with the shared
    system prompt marked for prompt caching (ephemeral breakpoint) so it is
    billed once per cache window rather than once per request."""
    user_prompt = build_extraction_user_prompt(lu_number, expected_city, pages, current_year, **kwargs)
    return {
        "custom_id": custom_id,
        "params": {
            "model": model,
            "max_tokens": 8000,
            "system": _EXTRACTION_SYSTEM_BLOCKS,
            "messages": [{"role": "user", "content": user_prompt}],
        },
    }


def parse_extraction_text(text, stop_reason=None):
    if stop_reason is not None and stop_reason != "end_turn":
        raise ExtractionIncompleteError(f"stop_reason={stop_reason!r} (response truncated, not parsed)")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return json.loads(text)
