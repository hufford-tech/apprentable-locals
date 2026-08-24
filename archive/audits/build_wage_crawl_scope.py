from __future__ import annotations
# Archived one-off script. Kept for reproducibility; not part of the active pipeline.
# Run from the repository root:  python archive/audits/build_wage_crawl_scope.py
# The path insert below lets it still import the core modules that live in the root.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")))

"""Scope a future targeted wage crawl from review-tier rows and observed links."""


import csv
import os
import re
from collections import defaultdict
from urllib.parse import urljoin

csv.field_size_limit(10_000_000)

LINK_RE = re.compile(r"\[([^\]]{1,180})\]\(([^)\s]+)(?:\s+[^)]*)?\)", re.I)
HTML_LINK_RE = re.compile(r"<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.I | re.S)
WAGE_LINK = re.compile(r"(?:wage|pay|scale|rate|cba|agreement|benefit)", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def page_files(lu, domains):
    roots = [os.path.join("raw", "crawl", "local", lu)] + [os.path.join("raw", "crawl", "jatc", d) for d in domains]
    out = []
    for root in roots:
        if os.path.isdir(root):
            out.extend(os.path.join(root, n) for n in os.listdir(root) if n.endswith(".md"))
    return sorted(set(out))


def scan_links(path):
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return []
    first = text.splitlines()[0].strip() if text.splitlines() else ""
    links = []
    for m in LINK_RE.finditer(text):
        links.append((m.group(2), m.group(1)))
    for m in HTML_LINK_RE.finditer(text):
        links.append((m.group(1), TAG_RE.sub(" ", m.group(2))))
    found = []
    for href, anchor in links:
        if WAGE_LINK.search(href) or WAGE_LINK.search(anchor):
            found.append((urljoin(first, href) if first else href, anchor.strip(), path.replace("\\", "/")))
    if first and WAGE_LINK.search(first):
        found.append((first, "observed wage-related page", path.replace("\\", "/")))
    return found


def main():
    reconciled = [r for r in load("out/wage_reconciled.csv") if r.get("tier") == "review"]
    targets = {r["lu_number"]: r for r in load("out/targets_with_population.csv")}
    domains = defaultdict(list)
    for r in load("out/local_to_jatc.csv"):
        domains[r["lu_number"]].append(r["jatc_domain"])
    total_population = sum(int(float(r.get("population") or 0)) for r in reconciled)
    fields = ["local_union_id", "lu_number", "charter_city", "population", "tier", "admitted_count", "best_candidate_quote", "likely_wage_page_url", "why_it_failed"]
    with open("out/wage_crawl_scope.csv", "w", newline="", encoding="utf-8") as f:
        f.write(f"# A targeted crawl would need {len(reconciled)} local page fetches and cover population {total_population:,}.\n")
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for row in reconciled:
            links = []
            for path in page_files(row["lu_number"], domains.get(row["lu_number"], [])):
                links.extend(scan_links(path))
            likely = links[0][0] if links else ""
            reasons = []
            if not row.get("effective_date"):
                reasons.append("no effective date")
            if row.get("effective_date_precision") == "year":
                reasons.append("year-only date")
            if row.get("consistency_check") == "insufficient_data":
                reasons.append("insufficient consistency data")
            if int(row.get("admitted_count") or 0) < 2:
                reasons.append("only one admitted candidate")
            if not likely:
                reasons.append("no observed wage-page link")
            w.writerow({
                "local_union_id": row["local_union_id"], "lu_number": row["lu_number"],
                "charter_city": row["charter_city"], "population": row["population"], "tier": row["tier"],
                "admitted_count": row["admitted_count"], "best_candidate_quote": row.get("evidence_quote", "")[:200],
                "likely_wage_page_url": likely, "why_it_failed": "; ".join(reasons) or "display bar not met",
            })
    print(f"review locals: {len(reconciled)}")
    print(f"targeted page fetches: {len(reconciled)}")
    print(f"population covered: {total_population:,}")


if __name__ == "__main__":
    main()
