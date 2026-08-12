"""Emit site/local/<slug>.html, one static SEO page per surviving local, plus
site/index.html (the finder), site/sitemap.xml, site/robots.txt (frontend task 5).

TRADEMARK NOTE: whether "IBEW" can appear in a domain name or product name is
unresolved. Descriptive use in a page title ("IBEW Local 134 Apprenticeship")
is a different legal question from using it as a brand name, and neither has
been cleared. This script does not pick a domain -- SITE_BASE_URL below is a
placeholder for canonical/OG tags and must be replaced before any real deploy.

Each page is self-contained and lightweight: only its own local's data, no
1.3 MB payload. Shared CSS lives in site/local.css so per-page HTML stays in
the 15-40 KB range.

Zero network, zero API cost. Reads out/frontend_data.json (already built by
build_frontend_data.py), out/jurisdictions.csv, out/zip_to_local.csv.
"""
import csv
import json
import math
import os
import re

csv.field_size_limit(10_000_000)

SITE_BASE_URL = "https://REPLACE-ME-BEFORE-DEPLOY.example"  # domain not cleared, see note above

SHOW_CONFIDENCE = True
STATUS_DISPLAY = True

LABEL = {
    "open": "Accepting applications now",
    "rolling": "Accepts applications on an ongoing basis",
    "closed_pending": "Not open yet",
    "closed": "Applications closed",
    "expired_data": "Last posted window has passed",
    "conflicting": "Conflicting information posted",
    "unknown": "Status not published",
}
NOTE = {
    "open": "A posted application window is open today.",
    "rolling": "This local takes applications year-round or on a repeating schedule.",
    "closed_pending": "A future window is posted. Get notified when it opens.",
    "closed": "The local has posted that applications are closed.",
    "expired_data": "The most recent window on their site has ended and nothing newer is posted.",
    "conflicting": "Their site says more than one thing. Confirm with the local before relying on this.",
    "unknown": "We could not confirm a status from their website. Contact the local directly.",
}


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def haversine(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


with open("out/frontend_data.json", encoding="utf-8") as f:
    bundle = json.load(f)
locals_ = bundle["locals"]
generated = bundle["generated"]

# full county / ZIP lists per local (frontend_data.json truncates counties to 40)
jurisdictions = load_csv("out/jurisdictions.csv")
counties_full = {}
for r in jurisdictions:
    if (r.get("jurisdiction_type") or "").strip().upper() != "I":
        continue
    counties_full.setdefault(r["local_union_id"], []).append({
        "name": r.get("census_match_name") or r.get("county_name", ""),
        "state": r.get("state_province", ""),
        "pop": int(float(r["population_current"])) if r.get("population_current") else 0,
    })
for lid in counties_full:
    counties_full[lid].sort(key=lambda c: -c["pop"])

zips_full = {}
for r in load_csv("out/zip_to_local.csv"):
    zips_full.setdefault(r["local_union_id"], set()).add(r["zip"].zfill(5))

slugs_seen = set()
os.makedirs("site/local", exist_ok=True)

CSS = """
:root{
  --bg:#0e1116; --panel:#151a22; --panel2:#1c222c; --line:#2a323f;
  --ink:#e8edf4; --ink2:#9aa7b8; --ink3:#6b7889;
  --accent:#f0a13a; --accent2:#ffc46b;
  --open:#39c46e; --rolling:#4aa3f0; --pending:#f0a13a; --closed:#e2564d;
  --unknown:#6b7889; --expired:#8a6d3b; --conflict:#a97bd6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent2);text-decoration:none} a:hover{text-decoration:underline}
.wrap{max-width:720px;margin:0 auto;padding:22px 18px 60px}
.topnav{font-size:12.5px;color:var(--ink3);margin-bottom:16px}
h1{font-size:26px;margin:6px 0 2px;letter-spacing:-.4px}
.sub{color:var(--ink2);font-size:14.5px;margin-bottom:16px}
.statusband{margin:15px 0;padding:13px 14px;border-radius:10px;background:var(--panel2);
  border:1px solid var(--line);border-left:3px solid var(--unknown)}
.statusband.open{border-left-color:var(--open)}
.statusband.rolling{border-left-color:var(--rolling)}
.statusband.closed_pending{border-left-color:var(--pending)}
.statusband.closed{border-left-color:var(--closed)}
.statusband.expired_data{border-left-color:var(--expired)}
.statusband.conflicting{border-left-color:var(--conflict)}
.slabel{font-size:15px;font-weight:640}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:1px}
.s-open{background:var(--open)} .s-rolling{background:var(--rolling)}
.s-closed_pending{background:var(--pending)} .s-closed{background:var(--closed)}
.s-expired_data{background:var(--expired)} .s-unknown{background:var(--unknown)}
.s-conflicting{background:var(--conflict)}
.sconf{display:inline-block;margin-left:8px;font-size:10px;text-transform:uppercase;letter-spacing:.7px;
  padding:2px 7px;border-radius:20px;background:#2a323f;color:var(--ink2);font-weight:600;vertical-align:1.5px}
.snote{font-size:12.5px;color:var(--ink3);margin-top:6px}
.quote{font-size:12.5px;color:var(--ink2);margin-top:9px;padding:9px 11px;background:var(--bg);
  border-radius:7px;border-left:2px solid var(--line);font-style:italic}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:16px 0}
.cell{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:11px 12px}
.cell b{display:block;font-size:19px;letter-spacing:-.3px}
.cell span{font-size:10.5px;color:var(--ink3);text-transform:uppercase;letter-spacing:.7px}
.cell small{display:block;font-size:10.5px;color:var(--ink3);margin-top:3px}
h2{font-size:11px;text-transform:uppercase;letter-spacing:.9px;color:var(--ink3);margin:22px 0 9px}
.row{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.row span{color:var(--ink3);flex:none} .row b{font-weight:520;text-align:right}
.muted{color:var(--ink3);font-style:italic}
.btn{display:block;width:100%;padding:12px;border-radius:9px;text-align:center;font-weight:640;
  font-size:14px;cursor:pointer;border:1px solid var(--line);background:var(--panel2);color:var(--ink);
  margin-top:9px}
.btn.primary{background:linear-gradient(160deg,var(--accent),#d4841f);color:#1a1206;border:none}
details{margin-top:6px} summary{cursor:pointer;color:var(--accent2);font-size:13px;padding:4px 0}
.zips{font-size:12px;color:var(--ink2);line-height:1.8;max-height:220px;overflow-y:auto;margin-top:8px}
.counties{font-size:13px;color:var(--ink2);line-height:1.9}
.nearby{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.nearby a{background:var(--panel2);border:1px solid var(--line);border-radius:20px;padding:6px 12px;font-size:12.5px}
footer{margin-top:26px;font-size:11.5px;color:var(--ink3)}
:root:focus-within .btn:focus,a:focus{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:480px){.grid{grid-template-columns:1fr}}
"""

with open("site/local.css", "w", encoding="utf-8") as f:
    f.write(CSS.strip() + "\n")


def status_block_html(l):
    if not STATUS_DISPLAY:
        return ('<div class="statusband"><div class="slabel">Check with the local</div>'
                '<div class="snote">Application windows change often. Use the official link below.</div></div>')
    conf = f'<span class="sconf">{esc(l["conf"])} confidence</span>' if SHOW_CONFIDENCE else ""
    ev = ""
    if SHOW_CONFIDENCE and l.get("quote"):
        src = f' <a href="{esc(l["src"])}" target="_blank" rel="noopener">source</a>' if l.get("src") else ""
        ev = f'<div class="quote">&ldquo;{esc(l["quote"])}&rdquo;{src}</div>'
    nx = f'<div class="snote" style="color:var(--accent2)">Next window opens {esc(l["next_open"])}</div>' if l.get("next_open") else ""
    return (f'<div class="statusband {l["status"]}"><div class="slabel">'
            f'<span class="dot s-{l["status"]}"></span>{LABEL[l["status"]]}{conf}</div>'
            f'<div class="snote">{NOTE[l["status"]]}</div>{nx}{ev}</div>')


def cta_block_html(l):
    alert = ""
    if l.get("next_open") or STATUS_DISPLAY:
        alert = (f'<a class="btn" href="mailto:?subject=Notify%20me%20-%20IBEW%20Local%20{l["lu"]}" '
                 f'aria-label="Get notified when Local {l["lu"]} opens applications">'
                 f'Email me when Local {l["lu"]} opens</a>')
    return (f'<a class="btn primary" href="../index.html" aria-label="Practice the aptitude test and interview">'
            f'Practice the aptitude test &amp; interview</a>{alert}')


def page_html(l, nearest):
    city, st, lu = l["city"], l["st"], l["lu"]
    title = f"IBEW Local {lu} Apprenticeship — {city}, {st} | Inside Wireman Program"
    pop_txt = f"{l['pop']:,}" if l.get("pop") else "an unpublished"
    desc = (f"IBEW Local {lu} in {city}, {st} serves {pop_txt} people across {l['county_n']} "
            f"counties. Inside wireman apprenticeship status, requirements, and how to apply.")
    canonical = f"{SITE_BASE_URL}/local/{l['slug']}.html"

    req = [("Minimum age", l.get("min_age")), ("Education", l.get("min_edu")), ("Aptitude test", l.get("aptitude"))]
    req = [(k, v) for k, v in req if v and str(v).strip()]

    counties = counties_full.get(l["id"], [])
    county_html = " &middot; ".join(esc(f'{c["name"]}, {c["state"]}') for c in counties) or '<span class="muted">Not on file</span>'

    zips = sorted(zips_full.get(l["id"], ()))
    zip_html = ", ".join(zips) if zips else '<span class="muted">Not on file</span>'

    website = l.get("website", "")
    website_href = website if website.startswith("http") else f"https://{website}" if website else ""

    nearby_html = "".join(
        f'<a href="{n["slug"]}.html">Local {n["lu"]} ({esc(n["city"])}, {n["st"]}) &middot; {n["dist"]:.0f} mi</a>'
        for n in nearest
    )

    jsonld = {
        "@context": "https://schema.org",
        "@type": "EducationalOccupationalProgram",
        "name": f"IBEW Local {lu} Inside Wireman Apprenticeship",
        "description": desc,
        "provider": {
            "@type": "Organization",
            "name": f"IBEW Local {lu}" + (f" ({l['jatc']})" if l.get("jatc") else ""),
            "url": website_href or canonical,
        },
        "occupationalCategory": "47-2111.00",
        "areaServed": {
            "@type": "AdministrativeArea",
            "name": f"{l['county_n']} counties served by IBEW Local {lu}, headquartered in {city}, {st}",
        },
        "educationalProgramMode": "https://schema.org/OnSitePlacement",
        "programType": "Apprenticeship",
    }
    if l.get("app_url"):
        jsonld["applicationStartDate"] = ""
        jsonld["url"] = l["app_url"]
    if l.get("next_open"):
        jsonld["applicationDeadline"] = l["next_open"]
    jsonld = {k: v for k, v in jsonld.items() if v != ""}

    apply_rows = []
    if l.get("app_url"):
        apply_rows.append(f'<div class="row"><span>Application page</span><b><a href="{esc(l["app_url"])}" target="_blank" rel="noopener">Official link &rarr;</a></b></div>')
    else:
        apply_rows.append('<div class="row"><span>Application page</span><b class="muted">Not published</b></div>')
    if website_href:
        apply_rows.append(f'<div class="row"><span>Local website</span><b><a href="{esc(website_href)}" target="_blank" rel="noopener">{esc(website)}</a></b></div>')
    if l.get("phone"):
        apply_rows.append(f'<div class="row"><span>Phone</span><b><a href="tel:{esc(re_digits(l["phone"]))}">{esc(l["phone"])}</a></b></div>')
    if l.get("email"):
        apply_rows.append(f'<div class="row"><span>Email</span><b><a href="mailto:{esc(l["email"])}">{esc(l["email"])}</a></b></div>')
    if l.get("meets"):
        apply_rows.append(f'<div class="row"><span>Meetings</span><b style="max-width:260px">{esc(l["meets"])}</b></div>')

    req_html = ""
    if req:
        req_html = "<h2>Requirements</h2>" + "".join(
            f'<div class="row"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in req)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="../local.css">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<script type="application/ld+json">{json.dumps(jsonld)}</script>
</head>
<body>
<div class="wrap">
  <div class="topnav"><a href="../index.html">&larr; Back to the IBEW Apprenticeship Finder</a></div>
  <h1>IBEW Local {esc(lu)}</h1>
  <div class="sub">{esc(city)}, {esc(st)}{f' &middot; {esc(l["jatc"])}' if l.get("jatc") else ''}</div>

  {status_block_html(l)}

  {cta_block_html(l)}

  <div class="grid">
    <div class="cell"><b>{l['pop']:,}</b><span>People in jurisdiction</span>
      {f'<small>#{l["rank"]} of 245 nationally</small>' if l.get('rank') else ''}</div>
    <div class="cell"><b>{f"{l['members']:,}" if l.get('members') else '—'}</b><span>Union members</span>
      <small>{'DOL filing, FY2025' if l.get('members') else 'Not filed'}</small></div>
    <div class="cell"><b>{l['county_n']}</b><span>Counties covered</span></div>
    <div class="cell"><b>{l['zip_n']:,}</b><span>ZIP codes</span></div>
  </div>

  <h2>Apprentice pay</h2>
  <div class="row"><span>Starting wage</span><b class="muted">Not yet collected</b></div>
  <div class="row"><span>Journeyman scale</span><b class="muted">Not yet collected</b></div>

  {req_html}

  <h2>Apply</h2>
  {''.join(apply_rows)}

  <h2>Counties served ({l['county_n']})</h2>
  <div class="counties">{county_html}</div>

  <h2>ZIP codes served ({l['zip_n']:,})</h2>
  <details><summary>Show all ZIP codes</summary><div class="zips">{esc(zip_html)}</div></details>

  <h2>Nearby locals</h2>
  <div class="nearby">{nearby_html or '<span class="muted">None on file</span>'}</div>

  <footer>Data current as of {generated}. Application status and requirements come from each
  local's own website and can change without notice &mdash; confirm with the local before relying
  on this page. &copy; IBEW Apprenticeship Finder.</footer>
</div>
</body>
</html>
"""


def re_digits(s):
    return "".join(ch for ch in s if ch.isdigit() or ch == "+")


pages_written = []
for l in locals_:
    slug = l["slug"]
    if slug in slugs_seen:
        raise SystemExit(f"duplicate slug: {slug}")
    slugs_seen.add(slug)

    dists = []
    for o in locals_:
        if o["id"] == l["id"]:
            continue
        d = haversine(l["lat"], l["lon"], o["lat"], o["lon"])
        dists.append({**o, "dist": d})
    dists.sort(key=lambda x: x["dist"])
    nearest = dists[:5]

    html = page_html(l, nearest)
    path = f"site/local/{slug}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    pages_written.append((slug, os.path.getsize(path)))

# ---- site/index.html: finder built from page_template.html --------------------
with open("page_template.html", encoding="utf-8") as f:
    template = f.read()
with open("out/frontend_data.json", encoding="utf-8") as f:
    payload = f.read()
index_html = template.replace("__DATA__", payload)
os.makedirs("site", exist_ok=True)
with open("site/index.html", "w", encoding="utf-8") as f:
    f.write(index_html)

# ---- sitemap.xml + robots.txt --------------------------------------------------
urls = [f"{SITE_BASE_URL}/index.html"] + [f"{SITE_BASE_URL}/local/{l['slug']}.html" for l in locals_]
sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for u in urls:
    sitemap.append(f"  <url><loc>{u}</loc><lastmod>{generated}</lastmod></url>")
sitemap.append("</urlset>")
with open("site/sitemap.xml", "w", encoding="utf-8") as f:
    f.write("\n".join(sitemap) + "\n")

with open("site/robots.txt", "w", encoding="utf-8") as f:
    f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE_BASE_URL}/sitemap.xml\n")

sizes = sorted(sz for _, sz in pages_written)
print(f"local pages written: {len(pages_written)}")
print(f"page size: min {sizes[0]/1024:.1f} KB, median {sizes[len(sizes)//2]/1024:.1f} KB, "
      f"max {sizes[-1]/1024:.1f} KB")
print(f"site/index.html: {os.path.getsize('site/index.html')/1024:.0f} KB")
print(f"unique slugs: {len(slugs_seen)}")
