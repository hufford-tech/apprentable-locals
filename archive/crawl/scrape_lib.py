import csv
import json
import re
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

from firecrawl import Firecrawl

KEYWORDS = [
    "apprentic", "training", "jatc", "etp", "apply", "application",
    "become", "recruit", "aptitude", "wireman", "education", "career",
]

FC = None


def fc_client():
    global FC
    if FC is None:
        FC = Firecrawl()
    return FC


def credits_remaining():
    return fc_client().get_credit_usage().remaining_credits


def load_targets(path="out/scrape_targets.csv"):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalize_url(u):
    u = u.strip()
    if not u:
        return None
    if not u.lower().startswith("http"):
        u = "http://" + u
    return u


def scrape_one(url, formats=None):
    """Single scrape call. Returns (document_or_None, error_str_or_None)."""
    formats = formats or ["markdown", "links"]
    try:
        doc = fc_client().scrape(url, formats=formats)
        return doc, None
    except Exception as e:
        return None, str(e)


def extract_markdown_links(markdown_text):
    """Parse [anchor text](url) pairs directly out of markdown -- Firecrawl's
    'links' format returns bare URLs with no anchor text, but the markdown
    body itself preserves inline link text."""
    if not markdown_text:
        return []
    pattern = re.compile(r"\[([^\]]*)\]\((https?://[^\s)]+)\)")
    return [(text.strip(), url.strip()) for text, url in pattern.findall(markdown_text)]


def domain_of(url):
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def rank_candidate(url, anchor_text, home_domain):
    """Lower rank number = higher priority. Returns (rank, reason) or None if no match."""
    path = urlparse(url).path.lower()
    text = (anchor_text or "").lower()
    dom = domain_of(url)
    is_external = dom != home_domain

    # exact /apprenticeship-ish path, highest priority
    if re.search(r"/apprentic", path):
        return (0, "exact apprenticeship path match")

    if is_external and ("jatc" in dom or "training" in dom):
        return (1, f"external domain matches jatc/training ({dom})")

    haystack = f"{path} {text}"
    for kw in KEYWORDS:
        if kw in haystack:
            return (2, f"keyword match: '{kw}'")

    return None


def discover_candidates(home_url, links, markdown_text, cap=4):
    """links: flat list of URLs from Firecrawl 'links' format.
    markdown_text: home page markdown, used to recover anchor text.
    Returns list of dicts: url, is_external, match_reason, rank (sorted, capped)."""
    home_domain = domain_of(home_url)
    anchor_map = {}
    for text, url in extract_markdown_links(markdown_text):
        anchor_map.setdefault(url, text)

    seen = set()
    scored = []
    for url in links or []:
        if url in seen:
            continue
        seen.add(url)
        anchor_text = anchor_map.get(url, "")
        result = rank_candidate(url, anchor_text, home_domain)
        if result is None:
            continue
        rank, reason = result
        is_external = domain_of(url) != home_domain
        scored.append({
            "candidate_url": url,
            "is_external": is_external,
            "match_reason": reason,
            "rank": rank,
        })

    scored.sort(key=lambda c: c["rank"])
    return scored[:cap]


def anthropic_client():
    import anthropic
    return anthropic.Anthropic()


EXTRACTION_SYSTEM_PROMPT = """You extract IBEW apprenticeship program facts from scraped web page markdown for a single local union (LU).

Rules, follow exactly:
- Never infer or guess. If a fact is absent from the page text, leave its field empty and lower confidence accordingly.
- accepting_applications is "unknown" unless the page explicitly states current application status.
- A phrase like "applications accepted first two weeks of March" is NOT a date. Leave app_window_open/app_window_close empty and put the verbatim phrase in app_window_description.
- A date with no year is not a usable ISO date. Do not fabricate a year.
- If the page content appears to describe a different IBEW local than the expected LU number, set confidence to "low" and mention the mismatch in other_requirements or leave a note -- do not silently substitute.
- evidence_quote must be copied verbatim from the source text and must be under 15 words. It should support/justify the application window dates or status you extracted.
- source_url must be one of the URLs provided to you for this local.
- Output ONLY a single JSON object matching the exact schema given in the user message. No prose, no markdown fences, no commentary.
"""


def build_extraction_user_prompt(lu_number, expected_city, pages):
    """pages: list of (url, markdown_text)"""
    parts = [
        f"Expected local union number: LU {lu_number} ({expected_city}).",
        "Below are one or more scraped pages (homepage plus any apprenticeship/JATC candidate pages) for this local.",
        "Extract into exactly this JSON schema (all keys required, use null/empty string/empty array/\"unknown\" where a fact is absent):",
        json.dumps({
            "has_apprenticeship": "bool",
            "program_name": "string",
            "jatc_name": "string",
            "jatc_domain": "string",
            "application_url": "string",
            "accepting_applications": "yes | no | unknown",
            "app_window_open": "ISO date string or empty",
            "app_window_close": "ISO date string or empty",
            "app_window_description": "verbatim phrase or empty",
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
            "evidence_quote": "verbatim, under 15 words",
            "source_url": "string, one of the page URLs below",
            "confidence": "high | medium | low",
        }, indent=2),
        "",
        "PAGES:",
    ]
    for url, md in pages:
        parts.append(f"\n=== SOURCE URL: {url} ===\n{md[:15000]}")
    return "\n".join(parts)


def call_extraction(lu_number, expected_city, pages, model="claude-sonnet-4-6"):
    client = anthropic_client()
    user_prompt = build_extraction_user_prompt(lu_number, expected_city, pages)
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip()
    # strip markdown fences if the model added them despite instructions
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return json.loads(text), resp.usage
