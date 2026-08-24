"""
Monthly snapshot + diff of asksparkyai.com's IBEW local coverage.

Analysis only: stores URL, inferred local_number, and sitemap lastmod.
Does NOT fetch, store, or reuse any of their page content.

Usage:
    python3 diff_sparky.py            # take today's snapshot, diff vs most recent prior snapshot
"""
import datetime
import glob
import json
import os
import re
import subprocess

SITEMAP_URL = "https://asksparkyai.com/sitemap.xml"
SNAPSHOT_DIR = os.path.dirname(os.path.abspath(__file__))

LOCAL_SLUG_RE = re.compile(r"/ibew-locals/local-(\d+)-")


def fetch_sitemap():
    raw_path = os.path.join(SNAPSHOT_DIR, "_raw_sitemap_tmp.xml")
    subprocess.run(
        ["curl", "-s", "-A", "Mozilla/5.0 (compatible; research-bot)", SITEMAP_URL, "-o", raw_path],
        check=True,
    )
    with open(raw_path, encoding="utf-8") as f:
        content = f.read()
    os.remove(raw_path)
    return content


def extract_locals(sitemap_xml):
    entries = re.findall(r"<url>\s*<loc>([^<]+)</loc>\s*<lastmod>([^<]*)</lastmod>", sitemap_xml)
    out = []
    for url, lastmod in entries:
        if "/ibew-locals/" not in url:
            continue
        if url.rstrip("/").endswith("/ibew-locals"):
            continue
        m = LOCAL_SLUG_RE.search(url)
        local_number = m.group(1) if m else None
        out.append({"url": url, "local_number": local_number, "lastmod": lastmod})
    return out


def latest_prior_snapshot(today_path):
    existing = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, "sparky_snapshot_*.json")))
    existing = [p for p in existing if os.path.abspath(p) != os.path.abspath(today_path)]
    return existing[-1] if existing else None


def main():
    today = datetime.date.today().isoformat()
    out_path = os.path.join(SNAPSHOT_DIR, f"sparky_snapshot_{today}.json")

    sitemap_xml = fetch_sitemap()
    locals_list = extract_locals(sitemap_xml)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(locals_list, f, indent=2)

    print(f"Snapshot saved: {out_path}")
    print(f"Local detail pages found: {len(locals_list)}")

    lastmods = sorted(set(e["lastmod"] for e in locals_list))
    if len(lastmods) == 1:
        print(f"All entries share one lastmod ({lastmods[0]}) -- this is a sitemap build stamp, "
              f"not per-page edit history. Cannot infer individual add dates from lastmod alone; "
              f"rely on month-over-month URL diffs instead.")
    else:
        print(f"lastmod values vary ({len(lastmods)} distinct) -- may carry real edit-history signal.")

    prior_path = latest_prior_snapshot(out_path)
    if not prior_path:
        print("\nNo prior snapshot found -- nothing to diff against yet. Re-run next month.")
        return

    with open(prior_path, encoding="utf-8") as f:
        prior_list = json.load(f)

    prior_numbers = {e["local_number"] for e in prior_list if e["local_number"]}
    current_numbers = {e["local_number"] for e in locals_list if e["local_number"]}

    added = sorted(current_numbers - prior_numbers, key=lambda x: int(x))
    removed = sorted(prior_numbers - current_numbers, key=lambda x: int(x))

    print(f"\nDiff vs {os.path.basename(prior_path)}:")
    print(f"  Locals added: {len(added)} {added if added else ''}")
    print(f"  Locals removed: {len(removed)} {removed if removed else ''}")


if __name__ == "__main__":
    main()
