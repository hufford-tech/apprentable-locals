"""Build-time internal link check.

Scans every generated HTML artifact (ibew_finder.html at the repo root, plus
everything under site/) for href="..." values that look like a real relative
file path -- not http(s)/mailto/tel/javascript/data/anchor-only, and not a JS
template literal still containing ${...} interpolation (those are runtime,
not static, and can't be resolved here) -- and verifies the target actually
exists on disk relative to the linking file's own directory.

Exits nonzero and prints every broken link if any target is missing. Run as
the last step of the build so a broken internal link fails the build loudly
instead of shipping a 404.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HREF_RE = re.compile(r'\bhref="([^"]*)"')

SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "javascript:", "data:", "#")


def internal_targets(html_path):
    text = html_path.read_text(encoding="utf-8", errors="replace")
    for m in HREF_RE.finditer(text):
        href = m.group(1)
        if not href or href.startswith(SKIP_PREFIXES) or "${" in href:
            continue
        yield href


def check_file(html_path):
    broken = []
    for href in internal_targets(html_path):
        path_part = href.split("#", 1)[0].split("?", 1)[0]
        if not path_part:
            continue
        if path_part.startswith("/"):
            target = ROOT / "site" / path_part.lstrip("/")
        else:
            target = (html_path.parent / path_part).resolve()
        if not target.is_file():
            broken.append((href, target))
    return broken


def main():
    html_files = [ROOT / "ibew_finder.html"] + sorted((ROOT / "site").rglob("*.html"))
    html_files = [f for f in html_files if f.is_file()]

    all_broken = []
    for f in html_files:
        for href, target in check_file(f):
            all_broken.append((f.relative_to(ROOT), href, target))

    print(f"Checked {len(html_files)} HTML files for internal links.")
    if all_broken:
        print(f"\n[FAIL] {len(all_broken)} broken internal link(s):")
        for src, href, target in all_broken:
            print(f"  {src}: href=\"{href}\" -> missing {target}")
        raise SystemExit(1)

    print("All internal links resolve to files on disk.")


if __name__ == "__main__":
    main()
