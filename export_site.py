#!/usr/bin/env python3
"""Export the built static site into a clean, deployable folder.

Why this exists: the ibew repo is a data pipeline (raw/ alone is 7,000+ files
and 236MB). Vercel clones the whole repo on every build, so deploying this
repo directly means a 400MB clone per deploy. Only site/ is actually served.

This is also the merge step. Today it targets a standalone deploy folder; when
the pages move onto apprentable.org, the same command points at the Next app's
public directory and nothing else changes:

    python export_site.py --dest deploy --noindex          # test deploy
    python export_site.py --dest ../apprentable/public     # the eventual merge

URLs are emitted WITHOUT the .html extension, matching what Next.js routes will
serve after the merge. Vercel's cleanUrls handles the mapping. Getting this
right now is what avoids 244 redirects later.
"""

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"

VERCEL_CONFIG = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))

NOINDEX_HEADERS = [
    {
        "source": "/(.*)",
        "headers": [
            {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
        ],
    }
]

ROBOTS_NOINDEX = """User-agent: *
Disallow: /
"""


def clean_urls_in_text(text: str) -> str:
    """Drop the .html extension from internal links, canonicals and sitemap locs.

    Only touches paths that look like our own generated pages. Leaves external
    URLs, asset paths (.css/.js/.json) and anything with a query string alone.
    """
    text = re.sub(r'(href=")([^"]*?)/index\.html(")', r"\1\2/\3", text)
    text = re.sub(r'(href=")index\.html(")', r"\1/\2", text)
    text = re.sub(r'(href="[^"]*?/?[a-z0-9][a-z0-9\-]*)\.html(")', r"\1\2", text)
    # Links built at runtime as JS template literals, e.g.
    # href="locals/${l.slug}.html" in the finder. Without this they still work,
    # but every click from the index takes a 308 redirect first.
    text = re.sub(r'(href="[^"]*\$\{[^"}]*\})\.html(")', r"\1\2", text)
    text = re.sub(r"(<loc>[^<]*?)/index\.html(</loc>)", r"\1/\2", text)
    text = re.sub(r"(<loc>[^<]*?)\.html(</loc>)", r"\1\2", text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True,
                    help="output directory (created/overwritten)")
    ap.add_argument("--noindex", action="store_true",
                    help="block search engines: robots Disallow plus an "
                         "X-Robots-Tag header. Use for any deploy that is not "
                         "the real apprentable.org launch.")
    ap.add_argument("--no-vercel-json", action="store_true",
                    help="skip writing vercel.json (use when exporting into a "
                         "Next.js app that already has its own config)")
    args = ap.parse_args()

    if not SITE.exists():
        raise SystemExit(f"[blocker] {SITE} not found -- run build_local_pages.py first")

    dest = Path(args.dest).resolve()
    if dest == ROOT or ROOT in dest.parents and dest.name in {"site", "out", "raw"}:
        raise SystemExit(f"[blocker] refusing to export over {dest}")

    stale_warning = False
    if dest.exists():
        try:
            shutil.rmtree(dest)
        except OSError:
            # Some mounts disallow unlink. Copy over the top instead and say so:
            # files removed since the last export would otherwise linger silently.
            stale_warning = True
    # The source site can contain local Vercel linkage and environment files.
    # A deploy export must contain only public assets, never those local files.
    shutil.copytree(SITE, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".env*", ".vercel", ".gitignore", ".vercelignore"))

    rewritten = 0
    for p in sorted(dest.rglob("*")):
        if p.suffix.lower() not in {".html", ".xml", ".txt"}:
            continue
        original = p.read_text(encoding="utf-8", errors="replace")
        updated = clean_urls_in_text(original)
        if updated != original:
            p.write_text(updated, encoding="utf-8")
            rewritten += 1

    if args.noindex:
        (dest / "robots.txt").write_text(ROBOTS_NOINDEX, encoding="utf-8")
        sitemap = dest / "sitemap.xml"
        if sitemap.exists():
            try:
                sitemap.unlink()
            except OSError:
                # some mounts disallow unlink; an empty sitemap is equivalent
                sitemap.write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    '</urlset>\n', encoding="utf-8")

    if not args.no_vercel_json:
        cfg = dict(VERCEL_CONFIG)
        if args.noindex:
            cfg["headers"] = NOINDEX_HEADERS
        (dest / "vercel.json").write_text(json.dumps(cfg, indent=2) + "\n",
                                          encoding="utf-8")
    (dest / ".vercelignore").write_text(".env*\n.vercel\n.gitignore\n", encoding="utf-8")

    pages = len(list((dest / "locals").glob("*.html"))) if (dest / "locals").exists() else 0
    total = sum(1 for p in dest.rglob("*") if p.is_file())
    size_mb = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()) / 1_000_000

    if stale_warning:
        print(f"[warning] could not clear {dest} first; files deleted since the "
              f"last export may still be present")
    print(f"Exported to {dest}")
    print(f"  local pages: {pages}")
    print(f"  files: {total}  ({size_mb:.1f} MB)")
    print(f"  .html dropped from links/canonicals/sitemap in {rewritten} files")
    if args.noindex:
        print("  NOINDEX: robots.txt disallows all, sitemap removed, "
              "X-Robots-Tag header set")
    else:
        print("  INDEXABLE: this export is meant for the real launch")


if __name__ == "__main__":
    main()
