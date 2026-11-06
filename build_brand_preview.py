"""Build the Apprentable-branded finder.

Run ``python build_brand_preview.py`` for an inert local preview, or
``python build_brand_preview.py --production`` for the deployable site/index.html.
"""
import argparse
import base64
import json
import os
import re
import subprocess
from pathlib import Path

from build_page import FIRST_PAINT_KEYS, _apply_flags, _escape_for_script_tag, _redact_locals


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "brand_preview.html"


def reversed_logo_data_uri():
    guide = (ROOT / "apprentable-brand-guide-v3.html").read_text(encoding="utf-8")
    match = re.search(r'<div class="logo-dark">\s*<img src="(data:image/svg\+xml;base64,[^"]+)"', guide)
    if not match:
        raise ValueError("Reversed Apprentable lockup missing from brand guide")
    # Verify the embedded asset instead of copying an arbitrary string into HTML.
    base64.b64decode(match.group(1).split(",", 1)[1], validate=True)
    return match.group(1)


def build(production=False, show_confidence=False, status_display=True,
          wage_display=True, rapids_display=True, debug_events=False):
    template = (ROOT / "page_template.html").read_text(encoding="utf-8")
    css = (ROOT / "brand_preview.css").read_text(encoding="utf-8")
    logo = reversed_logo_data_uri()

    if not production:
        # Review pages have no canonical URL and do not send analytics or forms.
        template = re.sub(r'<link rel="canonical"[^>]+>\s*', '', template, count=1)
        template = re.sub(r'<!-- Vercel Web Analytics.*?</script>\s*<script defer src="/_vercel/insights/script\.js"></script>\s*', '', template,
                          count=1, flags=re.S)
        template = re.sub(r'<!-- Google Analytics \(GA4\).*?</script>\s*', '', template,
                          count=1, flags=re.S)
    title = ('Find Your IBEW Local | Apprentable' if production
             else 'Find your local | Apprentable design preview')
    robots = '' if production else '<meta name="robots" content="noindex,nofollow">\n'
    template = template.replace('<title>Find Your IBEW Local | Apprenticeship Finder</title>',
                                f'<title>{title}</title>\n{robots}'
                                '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                                '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
                                '<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@700;800&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">')
    template = template.replace('</style>', '\n' + css + '\n</style>', 1)

    header = '''<header>
  <div class="masthead-bottom">
    <div class="title-block">
      <div class="kicker">Apprenticeship Field Guide</div>
      <h1>Find Your Local.</h1>
      <p class="intro">Search by ZIP code or city. See the local, application details, and the next step.</p>
    </div>
    <div class="hstat">
      <div><b id="nLocals">0</b><span>Locals</span></div>
      <div><b id="nZips">0</b><span>ZIPs mapped</span></div>
      <div><b id="nPop">0</b><span>People covered</span></div>
    </div>
    <nav class="prepnav" aria-label="Site navigation">
      <a class="diagnostic-link" href="https://app.apprentable.org/diagnostic" target="_blank" rel="noopener" onclick="track('diagnostic_cta_clicked',{{surface:'header'}})">Take the Free Diagnostic</a>
      <a href="__DIRECTORY_HREF__">Browse All Locals</a>
      <a href="https://app.apprentable.org/interview" target="_blank" rel="noopener">Interview Prep</a>
    </nav>
  </div>
</header>'''
    template, n = re.subn(r'<header>.*?</header>', lambda _: header, template, count=1, flags=re.S)
    if n != 1:
        raise ValueError("Finder header not found")
    if template.count('<div class="map-pane">') != 1:
        raise ValueError("Map pane not found")
    footer = f'''<footer class="sitefoot">
  <div class="sitefoot-copy">This is an independent, unofficial resource. It is not affiliated with,
endorsed by, or sponsored by the International Brotherhood of Electrical Workers (IBEW), the
National Electrical Contractors Association (NECA), or any local union or Joint Apprenticeship
and Training Committee (JATC).</div>
  <img class="footer-brand" src="{logo}" alt="Apprentable">
  <span id="stamp" class="sronly"></span>
</footer>'''
    template, n = re.subn(r'<footer class="sitefoot">.*?</footer>', lambda _: footer,
                          template, count=1, flags=re.S)
    if n != 1:
        raise ValueError("Finder footer not found")

    if not production:
        # Search and map selection remain live, but preview forms are inert.
        if template.count("async function submitReport(){") != 1 or template.count("async function capture(lu,kind){") != 1:
            raise ValueError("Expected finder form handlers are missing")
        template = template.replace(
            "async function submitReport(){",
            "async function submitReport(){\n"
            "  const previewFine = document.getElementById('ri-fine');\n"
            "  if (previewFine) previewFine.textContent = 'Design preview: reports are not submitted.';\n"
            "  return;",
            1,
        )
        template = template.replace(
            "async function capture(lu,kind){",
            "async function capture(lu,kind){\n"
            "  const previewFine = cardBody.querySelector('.fine');\n"
            "  if (previewFine) previewFine.textContent = 'Design preview: notifications are not submitted.';\n"
            "  return;",
            1,
        )
    template = template.replace("stroke:'#4b5866'", "stroke:'#6887a2'")
    template = template.replace("stroke:'#7b8998'", "stroke:'#a9bbc8'")
    template = template.replace("fill:'#7c8998'", "fill:'#b8c4ca'")
    template = template.replace("stroke:'#0e1116'", "stroke:'#102238'")
    template = template.replace("fill:'#0e1116'", "fill:'#102238'")
    template = template.replace("setAttribute('stroke', '#0e1116')", "setAttribute('stroke', '#102238')")
    template = template.replace("setAttribute('stroke', '#ffc46b')", "setAttribute('stroke', '#f5c060')")

    # Keep this output at the repository root so existing local profile links
    # and directory links resolve exactly as they do in the normal single build.
    template = _apply_flags(template, show_confidence, status_display,
                            wage_display, rapids_display, debug_events)
    template = template.replace("__PROFILE_BASE__", "locals/" if production else "site/locals/")
    template = template.replace("__DIRECTORY_HREF__", "all-locals.html" if production else "site/all-locals.html")
    template = template.replace("__WAGE_METHOD_URL__", "wage-estimates.html" if production else "site/wage-estimates.html")
    data = json.loads((ROOT / "out/frontend_data.json").read_text(encoding="utf-8"))
    data = _redact_locals(data, show_confidence, status_display,
                          wage_display, rapids_display)
    if not data.get("locals") or not data.get("zips"):
        raise ValueError("Finder data is missing locals or ZIP mappings")
    if production:
        data_dir = ROOT / "site" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for key in ("zips", "zip_multi", "cities"):
            (data_dir / f"{key}.json").write_text(json.dumps(data[key], separators=(",", ":")), encoding="utf-8")
        first_paint = {key: value for key, value in data.items() if key in FIRST_PAINT_KEYS}
        first_paint.update(zips={}, zip_multi={}, cities={}, lean=True)
        data = first_paint
    output = template.replace("__DATA__", _escape_for_script_tag(json.dumps(data, separators=(",", ":"))))
    scripts = [match.group(2) for match in re.finditer(r'<script\b([^>]*)>(.*?)</script>', output, re.S | re.I)
               if 'application/json' not in match.group(1) and 'src=' not in match.group(1)]
    if len(scripts) < 2:
        raise ValueError("Finder scripts missing from preview")
    checked = subprocess.run(["node", "--check", "-"], input="\n".join(scripts),
                             text=True, encoding="utf-8", capture_output=True)
    if checked.returncode:
        raise ValueError(f"Preview JavaScript does not parse:\n{checked.stderr}")
    target = ROOT / "site" / "index.html" if production else OUTPUT
    target.write_text(output, encoding="utf-8")
    print(f"{target.relative_to(ROOT)} written: {target.stat().st_size / 1024:.0f} KB; "
          f"{len(data['locals'])} locals")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    build(production=args.production,
          show_confidence=os.environ.get("SHOW_CONFIDENCE", "false").lower() == "true",
          status_display=os.environ.get("STATUS_DISPLAY", "true").lower() != "false",
          wage_display=os.environ.get("WAGE_DISPLAY", "true").lower() != "false",
          rapids_display=os.environ.get("RAPIDS_DISPLAY", "true").lower() != "false",
          debug_events=os.environ.get("DEBUG_EVENTS", "false").lower() == "true")
