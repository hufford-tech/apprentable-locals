"""Recover missing application links from already-crawled local/JATC pages.

This script is intentionally file-only.  URLs are emitted only when observed
in a crawled page (relative links are resolved against that page's observed
URL, which does not invent a path).

FOR THE BUILD (Codex / Andrew): do not wire this in yet -- documenting the
contract here for whoever does.

  Column to read:  out/application_url_candidates.csv, rows where chosen=="true"
                    (at most one chosen row per lu_number). Use candidate_url
                    as the recovered application URL for that local.

  Fallback precedence when populating a local's application URL:
    1. existing non-empty, non-"False"/"True"/"None"/"nan" application_url
       from out/extraction_v2.csv (do not overwrite a real extracted value)
    2. the chosen candidate_url from this CSV, if present for that lu_number
    3. leave empty -- do not fabricate a URL

  See also out/string_leak_audit.csv (task 2): some application_url values
  are the literal string "False" and must be treated as empty, not as a
  real value, before applying step 1 above.
"""

from __future__ import annotations

import csv
import html
import os
import re
from collections import defaultdict
from urllib.parse import urljoin, urlparse

csv.field_size_limit(10_000_000)

OUT = "out/application_url_candidates.csv"
BLOCKERS = "out/round8_blockers.csv"

ANCHOR_RE = re.compile(r"\[([^\]]{1,180})\]\(([^)\s]+)(?:\s+[^)]*)?\)", re.I)
HTML_ANCHOR_RE = re.compile(r"<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.I | re.S)
FORM_RE = re.compile(r"<form\b[^>]*action\s*=\s*['\"]([^'\"]+)['\"]", re.I)
TAG_RE = re.compile(r"<[^>]+>")

TERM_RE = re.compile(
    r"\b(?:apply|application|apprentice|applicant|enroll|register|intake|"
    r"how\s+to\s+apply|start\s+your\s+application)\b",
    re.I,
)
THIRD_PARTY_RE = re.compile(
    r"(?:tradeschoolinc|apprenticeshipusa|jotform|formstack|google\.com/forms|"
    r"apply\.appion\.network|.gov/.*(?:apprent|application))",
    re.I,
)
PAGE_RE = re.compile(r"(?:apprent|applic|apply|enroll|register|intake|join)", re.I)
LOCAL_PAGE_RE = re.compile(r"(?:apprent|applic|apply|enroll|register|intake)", re.I)
NEGATIVE_RE = re.compile(
    r"(?:scholarship|voter|retiree|welfare|benefit|timecard|job\s+opening|"
    r"jobs?|career|employer|senator|politic|event|member\s+registration|"
    r"member\s+submission|report\s+abuse|donat|enter[- ]to[- ]win|letter|"
    r"book[- ]upgrade)", re.I,
)


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", value or ""))).strip()


def page_files(lu, jatc_domains):
    paths = []
    roots = [os.path.join("raw", "crawl", "local", lu)]
    roots.extend(os.path.join("raw", "crawl", "jatc", d) for d in jatc_domains)
    for root in roots:
        if os.path.isdir(root):
            paths.extend(os.path.join(root, name) for name in os.listdir(root) if name.endswith(".md"))
    return sorted(set(paths))


def read_page(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return "", ""
    first, _, _ = text.partition("\n")
    page_url = first.strip() if first.strip().startswith(("http://", "https://")) else ""
    return page_url, text


def is_usable_url(url):
    return bool(url and not url.startswith(("#", "javascript:", "mailto:", "tel:")))


def score_candidate(url, anchor_text, source_url, source_file, local_domains):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = (parsed.path + "?" + parsed.query).lower()
    text = anchor_text.lower()
    if NEGATIVE_RE.search(f"{url} {anchor_text}"):
        return -1, "negative_application_context"
    if "login" in path and not re.search(r"apply|application|register", path + " " + text, re.I):
        return -1, "login_not_application"
    if re.search(r"(?:user/register|civicrm/profile/create|reportabuse)", path, re.I):
        return -1, "account_or_report_form"
    if re.search(r"(?:dol\.gov|toolkitfaq)", host + path, re.I) and not re.search(r"apply|application|register", path + " " + text, re.I):
        return -1, "general_information_not_application"
    score = 0
    reasons = []
    own = any(d and (host == d or host.endswith("." + d)) for d in local_domains)
    if own:
        score += 20
        reasons.append("own_domain")
    if re.search(r"\bapply\b|\bapplication\b|how\s+to\s+apply|start\s+your\s+application", text, re.I):
        score += 40
        reasons.append("apply_anchor")
    if TERM_RE.search(text) or TERM_RE.search(url):
        score += 20
        reasons.append("application_term")
    if THIRD_PARTY_RE.search(url) and (re.search(r"apply|application|register|form", path, re.I) or re.search(r"apply|application", text, re.I)):
        score += 25
        reasons.append("third_party_host")
    if PAGE_RE.search(path):
        score += 15
        reasons.append("application_path")
    if LOCAL_PAGE_RE.search(source_url):
        score += 12
        reasons.append("source_apprenticeship_page")
    # A directly observed apprenticeship page is useful as a last-resort link,
    # but it must rank below an observed application destination.
    if url == source_url and LOCAL_PAGE_RE.search(source_url):
        score = 10
        reasons = ["apprenticeship_page_last_resort"]
    return score, ";".join(reasons)


def collect_for_local(target, domains):
    found = {}
    for source_file in page_files(target["lu_number"], domains):
        source_url, text = read_page(source_file)
        if not text:
            continue
        candidates = []
        for match in ANCHOR_RE.finditer(text):
            candidates.append((match.group(2), match.group(1)))
        for match in HTML_ANCHOR_RE.finditer(text):
            candidates.append((match.group(1), clean_text(match.group(2))))
        for match in FORM_RE.finditer(text):
            candidates.append((match.group(1), "form application handler"))

        for raw_url, anchor in candidates:
            raw_url = html.unescape(raw_url.strip())
            if not is_usable_url(raw_url):
                continue
            absolute = urljoin(source_url, raw_url) if source_url else raw_url
            if not (TERM_RE.search(anchor) or TERM_RE.search(raw_url) or THIRD_PARTY_RE.search(raw_url)):
                continue
            score, reason = score_candidate(absolute, clean_text(anchor), source_url, source_file, domains)
            if score <= 0:
                continue
            key = absolute.split("#", 1)[0]
            item = found.get(key)
            candidate = {
                "candidate_url": key,
                "anchor_text": clean_text(anchor)[:240],
                "source_file": source_file.replace("\\", "/"),
                "match_reason": reason,
                "score": score,
            }
            if item is None or candidate["score"] > item["score"]:
                found[key] = candidate

        # The page itself is an observed URL and is only eligible when its
        # path says it is an apprenticeship/application page.
        if (source_url and LOCAL_PAGE_RE.search(source_url)
                and not source_url.lower().endswith(".pdf")
                and not NEGATIVE_RE.search(source_url)):
            key = source_url.split("#", 1)[0]
            if key not in found:
                found[key] = {
                    "candidate_url": key,
                    "anchor_text": "observed apprenticeship page",
                    "source_file": source_file.replace("\\", "/"),
                    "match_reason": "apprenticeship_page_last_resort",
                    "score": 10,
                }
    return sorted(found.values(), key=lambda x: (-x["score"], x["candidate_url"]))


def main():
    targets = {r["lu_number"]: r for r in load("out/targets_with_population.csv")}
    extraction = {r["lu_number"]: r for r in load("out/extraction_v2.csv")}
    domains = defaultdict(list)
    for r in load("out/local_to_jatc.csv"):
        domains[r["lu_number"]].append(r["jatc_domain"].lower())
    missing = sorted((r for r in extraction.values() if not (r.get("application_url") or "").strip()), key=lambda r: int(r["lu_number"]))
    rows = []
    blockers = []
    chosen_count = 0
    for e in missing:
        target = targets.get(e["lu_number"], {})
        candidates = collect_for_local(target, domains.get(e["lu_number"], []))
        if not candidates:
            blockers.append({"task": "application_url_recovery", "lu_number": e["lu_number"], "details": "no observed application candidate in crawled local/JATC pages"})
        for rank, candidate in enumerate(candidates, 1):
            rows.append({
                "local_union_id": target.get("local_union_id", ""), "lu_number": e["lu_number"],
                "charter_city": target.get("charter_city", ""),
                "population": target.get("population_current_served_inside", ""),
                "candidate_url": candidate["candidate_url"], "anchor_text": candidate["anchor_text"],
                "source_file": candidate["source_file"], "match_reason": candidate["match_reason"],
                "rank": rank, "chosen": "true" if rank == 1 else "false",
            })
        if candidates:
            chosen_count += 1
            print(f"LU {e['lu_number']}: {candidates[0]['candidate_url']}")
        else:
            print(f"LU {e['lu_number']}: no observed candidate")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        fields = ["local_union_id", "lu_number", "charter_city", "population", "candidate_url", "anchor_text", "source_file", "match_reason", "rank", "chosen"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    fields = ["task", "lu_number", "details"]
    prior = []
    if os.path.exists(BLOCKERS) and os.path.getsize(BLOCKERS) > 0:
        with open(BLOCKERS, encoding="utf-8") as f:
            prior = [r for r in csv.DictReader(f) if r.get("task") != "application_url_recovery"]
    with open(BLOCKERS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(prior)
        w.writerows(blockers)
    print(f"missing locals: {len(missing)}; recovered: {chosen_count}; gaps: {len(missing) - chosen_count}; candidates: {len(rows)}")


if __name__ == "__main__":
    main()
