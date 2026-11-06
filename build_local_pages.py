"""Emit site/locals/<slug>.html, one static SEO page per surviving local, plus
site/index.html (the finder), site/sitemap.xml, site/robots.txt (frontend task 5).

SITE_BASE_URL is the public finder origin used for canonical URLs, sharing
metadata, and the sitemap.

Each page is self-contained and lightweight: only its own local's data, no
1.3 MB payload. Shared CSS lives in site/local.css so per-page HTML stays in
the 15-40 KB range.

Zero network, zero API cost. Reads out/frontend_data.json (already built by
build_frontend_data.py), out/jurisdictions.csv, out/zip_to_local.csv.
"""
import calendar
import csv
import json
import math
import os
import re
from datetime import date

csv.field_size_limit(10_000_000)

SITE_BASE_URL = "https://apprentable.org"
VERCEL_ANALYTICS_SNIPPET = """<script>
  window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
</script>
<script defer src="/_vercel/insights/script.js"></script>"""

# Task 13: same Supabase project/table the finder's capture() posts to
# (page_template.html CONFIG block) -- literal values duplicated here rather
# than shared at import time because this script has no runtime dependency on
# page_template.html today. Keep these two in sync with page_template.html by
# hand if the project ever rotates the anon key.
SUPABASE_URL = "https://tbkodgxqeibwfdrbmxyi.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_lJmIe0ZSszhaB4rG8TCfEg_PRbSVgCw"
REPORT_ISSUE_URL = f"{SUPABASE_URL}/functions/v1/report-issue"

# Task 9: single-constant switches, same contract as page_template.html's.
# Overridable via env for the flag-variant verification build in task 9/11 --
# the constants themselves are still what you'd flip for a real deploy.
SHOW_CONFIDENCE = os.environ.get("SHOW_CONFIDENCE", "false").lower() == "true"
STATUS_DISPLAY = os.environ.get("STATUS_DISPLAY", "true").lower() != "false"
WAGE_DISPLAY = os.environ.get("WAGE_DISPLAY", "true").lower() != "false"
# The refreshed estimate model validates at 36.4% median absolute percentage
# error on leave-one-out -- the 35-60% coarse band. If the model is
# ever regenerated and lands over 60%, set this back to "false" by hand; it is
# not read from the meta file automatically, same as every other display flag
# here being a hand-set single-constant switch.
RAPIDS_DISPLAY = os.environ.get("RAPIDS_DISPLAY", "true").lower() != "false"
DEBUG_EVENTS = os.environ.get("DEBUG_EVENTS", "false").lower() == "true"

INTAKE_META = {}
if os.path.exists("out/rapids_intake_meta.json"):
    with open("out/rapids_intake_meta.json", encoding="utf-8") as f:
        INTAKE_META = json.load(f)

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
    "expected_open": "The posted reopening date has passed. Confirm the current application window with the local before applying.",
    "rolling": "This local takes applications year-round or on a repeating schedule.",
    "closed_pending": "A future window is posted. Get notified when it opens.",
    "closed": "The local has posted that applications are closed.",
    "expired_data": "The most recent window on their site has ended and nothing newer is posted.",
    "conflicting": "Their site says more than one thing. Confirm with the local before relying on this.",
    "unknown": "We could not confirm a status from their website. Contact the local directly.",
}

# Task 12: candidate-facing display collapses compute_status.py's 8 raw
# computed_status values into 4 states. This is a presentation mapping ONLY,
# applied after compute_status.py has already run -- it never changes a
# computed status value, and compute_status.py itself is not touched.
#   open_now     <- open, expected_open (a stated reopen date has already
#                    passed, i.e. the local's own words say intake resumed)
#   always       <- rolling
#   opens_date   <- closed_pending, or closed with a known next_open_date
#                    (rule 7 in compute_status.py can attach one from a
#                    gate-rejected reopening statement)
#   unconfirmed  <- expired_data, conflicting, unknown, and closed with no
#                    next_open_date -- the three "we don't know" categories
#                    the brief calls out, plus a bare closure with nothing to
#                    go on. Rendered gray, never red: a closed local is a
#                    future application window / lead-capture opportunity,
#                    not a failure state.
DISPLAY_LABEL = {
    "open_now": "Open now",
    "always": "Always accepting",
    "opens_date": "Opens",  # date is appended by the caller
    "unconfirmed": "Unconfirmed – check with the local",
}
# Shape glyph shown next to the dot so color is never the only carrier of
# meaning (WCAG 1.4.1) -- colorblind users can't rely on red/green/gray/amber
# alone to tell these four states apart.
DISPLAY_SHAPE = {
    "open_now": "●",   # filled circle
    "always": "◆",     # diamond
    "opens_date": "▲", # triangle
    "unconfirmed": "■", # square
}


def display_state(status, next_open=None):
    """Collapse a raw computed_status value (+ next_open_date) into one of
    the 4 candidate-facing display states. Returns (key, label)."""
    if status in ("open", "expected_open"):
        return "open_now", DISPLAY_LABEL["open_now"]
    if status == "rolling":
        return "always", DISPLAY_LABEL["always"]
    if status == "closed_pending" or (status == "closed" and next_open):
        return "opens_date", f"Opens {fmt_date(next_open)}"
    return "unconfirmed", DISPLAY_LABEL["unconfirmed"]


def fmt_date(iso):
    if not iso:
        return ""
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{calendar.month_name[m]} {d}, {y}"


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def js_str(s):
    """Single-quoted JS string literal for use inside a double-quoted HTML
    attribute (onclick="..."). json.dumps() would emit double quotes and
    prematurely close the attribute -- this is not that."""
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


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

TODAY = date.today()

# Task 9: OUT_DIR lets the flag-variant verification build (task 9/11) render
# into a scratch directory instead of overwriting the real site/ output.
OUT_DIR = os.environ.get("OUT_DIR", "site")

slugs_seen = set()
os.makedirs(f"{OUT_DIR}/locals", exist_ok=True)

CSS = """
:root{
  --bg:#0e1116; --panel:#151a22; --panel2:#1c222c; --line:#2a323f;
  --ink:#e8edf4; --ink2:#9aa7b8; --ink3:#7c8998;
  --accent:#f0a13a; --accent2:#ffc46b;
  --open:#39c46e; --rolling:#4aa3f0; --pending:#f0a13a; --closed:#e2564d;
  --unknown:#6b7889; --expired:#8a6d3b; --conflict:#a97bd6;
  /* Task 12: the 4 candidate-facing display states. --d-unconfirmed is
     deliberately neutral gray, not red -- see DISPLAY_LABEL comment above. */
  --d-open:#39c46e; --d-always:#4aa3f0; --d-opens:#f0a13a; --d-unconfirmed:#7c8998;
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
  border:1px solid var(--line);border-left:3px solid var(--d-unconfirmed)}
.statusband.d-open_now{border-left-color:var(--d-open)}
.statusband.d-always{border-left-color:var(--d-always)}
.statusband.d-opens_date{border-left-color:var(--d-opens)}
.statusband.d-unconfirmed{border-left-color:var(--d-unconfirmed)}
.slabel{font-size:15px;font-weight:640}
/* Task 12: each state gets its own glyph (circle/diamond/triangle/square) as
   well as its own color, so meaning never rides on color alone (WCAG 1.4.1)
   -- a colorblind viewer still tells the 4 states apart by shape. */
.dot{display:inline-block;margin-right:7px;font-size:11px;vertical-align:1px}
.d-open_now .dot{color:var(--d-open)}
.d-always .dot{color:var(--d-always)}
.d-opens_date .dot{color:var(--d-opens)}
.d-unconfirmed .dot{color:var(--d-unconfirmed)}
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
.cell.est b{color:var(--accent2);border-bottom:1px dashed var(--accent2);padding-bottom:1px;display:inline-block}
.btn{display:block;width:100%;padding:12px;border-radius:9px;text-align:center;font-weight:640;
  font-size:14px;cursor:pointer;border:1px solid var(--line);background:var(--panel2);color:var(--ink);
  margin-top:9px}
.btn.primary{background:linear-gradient(160deg,var(--accent),#d4841f);color:#1a1206;border:none}
details{margin-top:6px} summary{cursor:pointer;color:var(--accent2);font-size:13px;padding:4px 0}
.zips{font-size:12px;color:var(--ink2);line-height:1.8;max-height:220px;overflow-y:auto;margin-top:8px}
.counties{font-size:13px;color:var(--ink2);line-height:1.9}
.nearby{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.nearby a{background:var(--panel2);border:1px solid var(--line);border-radius:20px;padding:6px 12px;font-size:12.5px}
.report-fab{position:fixed;right:18px;bottom:18px;z-index:1200;border:1px solid var(--line);
  border-radius:999px;background:var(--panel);color:var(--ink);padding:10px 14px;font-size:12px;
  font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.28);cursor:pointer}
.report-fab:hover{background:#232b36}
.issue-modal{position:fixed;inset:0;background:rgba(6,8,11,.72);z-index:2000;display:none;place-items:center;padding:20px}
.issue-modal.on{display:grid}
.issue-card{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:26px;max-width:420px;width:100%;max-height:92vh;overflow:auto}
.issue-card h2{margin:0 0 7px;font-size:19px;color:var(--ink);letter-spacing:-.3px;text-transform:none}
.issue-card p{margin:0 0 17px;color:var(--ink2);font-size:13.5px}
.issue-card label{display:block;font-size:12px;color:var(--ink2);margin:8px 0 4px}
.issue-card input,.issue-card select,.issue-card textarea{width:100%;padding:11px;border-radius:9px;border:1px solid var(--line);
  background:var(--bg);color:var(--ink);font-size:14px;outline:none;font-family:inherit}
.issue-card textarea{min-height:105px;resize:vertical;line-height:1.45}
.issue-card input:focus,.issue-card select:focus,.issue-card textarea:focus{border-color:var(--accent)}
.issue-close{float:right;color:var(--ink3);cursor:pointer;font-size:21px;line-height:1;margin:-4px -4px 0 0}
.issue-fine{font-size:11px;color:var(--ink3);margin-top:11px;line-height:1.5}
footer{margin-top:26px;font-size:11.5px;color:var(--ink3)}
:root:focus-within .btn:focus,a:focus{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:480px){.grid{grid-template-columns:1fr}}
"""

with open(f"{OUT_DIR}/local.css", "w", encoding="utf-8") as f:
    f.write(CSS.strip() + "\n")


def status_block_html(l):
    if not STATUS_DISPLAY:
        return ('<div class="statusband"><div class="slabel">Check with the local</div>'
                '<div class="snote">Application windows change often. Use the official link below.</div></div>')
    if l.get("program_applications"):
        app = l["program_applications"][0]
        return (f'<div class="statusband d-open_now"><div class="slabel">'
                f'<span class="dot" aria-hidden="true">{DISPLAY_SHAPE["open_now"]}</span>Accepting applications now</div>'
                f'<div class="snote">{esc(app["sponsor"])} lists {esc(app["program_name"])} applications as open. '
                f'Closes by {esc(app["close_by"])}; {esc(app["early_close_reason"])} '
                f'<a href="{esc(app["source_url"])}" target="_blank" rel="noopener">Check the official page</a>. '
                f'Checked {esc(app["verified_on"])}.</div></div>')
    # Task 12: candidate-facing band renders the 4-state display mapping, not
    # the raw 8-value computed_status -- see display_state() above.
    dkey, dlabel = display_state(l["status"], l.get("next_open"))
    conf = f'<span class="sconf">{esc(l["conf"])} confidence</span>' if SHOW_CONFIDENCE else ""
    ev = ""
    if SHOW_CONFIDENCE and l.get("quote"):
        src = f' <a href="{esc(l["src"])}" target="_blank" rel="noopener">source</a>' if l.get("src") else ""
        ev = f'<div class="quote">&ldquo;{esc(l["quote"])}&rdquo;{src}</div>'
    nc = ""
    if l.get("next_close"):
        prefix = "Open now, closes " if l["status"] == "open" else "Closes "
        nc = f'<div class="snote" style="color:var(--accent2)">{prefix}{fmt_date(l["next_close"])}.</div>'
    # NOTE text below the label still uses the original per-status copy
    # (LABEL/NOTE dicts) where it maps 1:1 -- for the collapsed buckets
    # (unconfirmed absorbing expired_data/conflicting/unknown/bare-closed) a
    # single neutral explanation is used instead of picking one raw NOTE.
    if dkey == "unconfirmed":
        note = "We could not confirm a current application window from the local's own site. Contact the local directly or use the official link below."
    elif dkey == "opens_date" and l["status"] != "closed_pending":
        note = "The local has posted that applications are closed, but a future window is on file. Get notified when it opens."
    else:
        note = NOTE.get(l["status"], NOTE["unknown"])
    return (f'<div class="statusband d-{dkey}"><div class="slabel">'
            f'<span class="dot" aria-hidden="true">{DISPLAY_SHAPE[dkey]}</span>{esc(dlabel)}{conf}</div>'
            f'<div class="snote">{note}</div>{nc}{ev}</div>')


def prep_snote_html(l):
    """Task 14: where the aptitude_test field is well-grounded (see the
    task-1 audit), reference what the local actually tests instead of
    generic copy. LU 456's aptitude_test text has zero grounding in its
    crawled source pages (confirmed fabrication) -- neutral copy only, never
    asserting specifics for that one local."""
    if str(l.get("lu")) == "456":
        return ""
    apt = (l.get("aptitude") or "").strip()
    if not apt:
        return ""
    return f'<div class="snote">Local {esc(l["lu"])} tests: {esc(apt[:180])}</div>'


def cta_block_html(l):
    lu_js = js_str(l["lu"])
    app = l.get("program_applications", [])
    official = (f'<a class="btn primary" href="{esc(l["app_url"])}" target="_blank" rel="noopener">'
                'Apply through the training program</a>') if app else ""
    prep = (f'<div class="snote">Preparing for Local {esc(l["lu"])}? '
            'See which math and reading skills to focus on.</div>'
            f'<a class="btn {"" if app else "primary"}" href="https://app.apprentable.org/diagnostic" target="_blank" rel="noopener" '
            f'aria-label="Take the free aptitude diagnostic while preparing for Local {l["lu"]}" '
            f'onclick="track(\'diagnostic_cta_clicked\',{{lu_number:{lu_js},surface:\'static\'}})">'
            'Take the Free Diagnostic</a>'
            '<div class="snote">No account needed to start. Sign in for the full skill breakdown.</div>'
            f'{prep_snote_html(l)}')
    if not app or "no personal interview" not in app[0].get("selection_process", "").lower():
        prep += (f'<a class="btn" href="https://app.apprentable.org/interview" target="_blank" rel="noopener" '
                 f'aria-label="Prepare for the interview for Local {l["lu"]}" '
                 f'onclick="track(\'prep_cta_clicked\',{{lu_number:{lu_js},surface:\'static\',product:\'interview\'}})">'
                 'Prepare for the interview</a>')
    notify = ""
    if not app and (l.get("next_open") or STATUS_DISPLAY):
        # Task 13: wired to the same Supabase `leads` endpoint the finder's
        # capture() posts to (same payload shape, same auth headers), plus
        # lu_number so the lead is attributable to this local. Replaces the
        # old bare `mailto:` that had no recipient and never sent anything.
        notify = (
            f'<div class="notifybox" id="notifybox-{esc(l["lu"])}">'
            f'<label for="nem-{esc(l["lu"])}" style="display:block;font-size:11px;color:var(--ink3);margin-top:9px">'
            f'Get notified when Local {esc(l["lu"])} opens</label>'
            f'<input id="nem-{esc(l["lu"])}" type="email" placeholder="you@email.com" '
            f'style="width:100%;padding:10px 11px;border-radius:8px;border:1px solid var(--line);'
            f'background:var(--bg);color:var(--ink);font-size:14px;margin-top:5px" '
            f'aria-label="Email address for Local {esc(l["lu"])} application alerts">'
            f'<input id="nhp-{esc(l["lu"])}" type="text" name="website" tabindex="-1" autocomplete="off" '
            f'aria-hidden="true" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0">'
            f'<button class="btn" onclick="notifyMe({lu_js})">Notify me</button>'
            f'<div class="fine" id="notifyfine-{esc(l["lu"])}" style="font-size:11.5px;color:var(--ink3);margin-top:6px"></div>'
            f'</div>'
        )
    return official + prep + notify


def wage_date(w):
    value = w.get("effective_date", "")
    if not value:
        return ""
    y, m, d = (int(x) for x in value.split("-"))
    if w.get("effective_precision") == "year":
        return str(y)
    if w.get("effective_precision") == "month":
        return f"{calendar.month_name[m]} {y}"
    return f"{calendar.month_name[m]} {d}, {y}"


def wage_range(low, high):
    if not low:
        return ""
    if not high or low == high:
        return f"${float(low):.2f}/hr"
    return f"${float(low):.2f}–${float(high):.2f}/hr"


NOT_PUBLISHED = '<span class="muted">Not published</span>'


def journeyman_tile(l, counties):
    """Prefer the reviewed program's base; label Davis-Bacon totals as packages."""
    programs = l.get("program_wages", []) if WAGE_DISPLAY else []
    if len(programs) == 1 and programs[0].get("journeyman_base"):
        p = programs[0]
        return (f'${float(p["journeyman_base"]):.2f}/hr',
                esc(p["program_name"]), "Journeyman base")
    w = l.get("wage") if WAGE_DISPLAY else None
    if not w or not w.get("total_low"):
        return NOT_PUBLISHED, "", "Journeyman base"
    value = esc(wage_range(w.get("total_low"), w.get("total_high")))
    # The wage pipeline (out/local_wage_davisbacon.csv) does not persist the
    # specific county its Davis-Bacon match came from, only the WD number --
    # the local's largest-population inside county is shown as the
    # jurisdiction reference instead of asserting it's the exact match.
    county_bit = f'{esc(counties[0]["name"])}, {esc(counties[0]["state"])}' if counties else ""
    wd = esc(w.get("wd_number", ""))
    bits = [b for b in [f"Davis-Bacon WD {wd}" if wd else "Davis-Bacon prevailing wage", county_bit] if b]
    return value, " &middot; ".join(bits), "Prevailing wage package"


def apprentice_tile(l):
    """Show one verified rate or a separate, rounded modeled range."""
    programs = l.get("program_wages", []) if WAGE_DISPLAY else []
    if len(programs) == 1:
        return f'${float(programs[0]["starting_rate"]):.2f}/hr'
    if len(programs) > 1:
        rates = [float(program["starting_rate"]) for program in programs]
        return wage_range(min(rates), max(rates))
    estimate = l.get("apprentice_wage_estimate") if WAGE_DISPLAY and not programs else None
    return f'~${estimate["low"]}–${estimate["high"]}/hr' if estimate else NOT_PUBLISHED


def estimate_evidence(estimate):
    outcomes = {
        "no_current_rate_published": "No current program rate found",
        "stale_source": "Available wage source is outdated",
        "ambiguous_program": "Program wage match is uncertain",
        "site_unavailable": "Official wage site was unavailable",
        "center_unresolved": "Training center is unconfirmed",
    }
    bits = [outcomes.get(estimate["research_outcome"], "No verified current rate")]
    if not estimate["center_verified"]:
        bits.append("Training center unconfirmed")
    return ". ".join(bits)


def apprentice_tile_note(l):
    programs = l.get("program_wages", []) if WAGE_DISPLAY else []
    if len(programs) == 1:
        program = programs[0]
        return (f'{esc(program["program_name"])} · <a href="{esc(program["source_url"])}" '
                'target="_blank" rel="noopener">Official wage source</a>')
    if len(programs) > 1:
        return 'Published wage zones · Official sources below'
    if WAGE_DISPLAY and l.get("apprentice_wage_estimate"):
        return (f'Regional model, not published pay · {esc(estimate_evidence(l["apprentice_wage_estimate"]))} · '
                '<a href="../wage-estimates.html">How calculated</a>')
    return ""


def intake_tile(l):
    """Tile 4 (round 2): annual apprentice intake, either the real reported
    figure (explicit LU or reviewed override, unrounded) or a
    peer-based modeled value (membership-scaled median, rounded).
    The rounding is deliberate: an unrounded estimate like "28" reads as
    reported, which is exactly the false precision this has to avoid."""
    if not RAPIDS_DISPLAY:
        return f'<b>{NOT_PUBLISHED}</b><span>Annual intake</span>', "cell"
    intake = l.get("intake")
    if not intake:
        return f'<b>{NOT_PUBLISHED}</b><span>Annual intake</span>', "cell"
    if intake["tier"] == "coverage_incomplete":
        return (f'<b>{NOT_PUBLISHED}</b><span>Annual intake</span>'
                f'<small>DOL registration data for {esc(intake["state"])} is incomplete.</small>'), "cell"
    fy = f"FY{intake['period_end'][:4]}" if intake.get("period_end") else "FY2025"
    if intake["tier"] == "confirmed":
        val = f'<b>{intake["value"]:,}</b>'
        label = f"Apprentices taken ({fy})"
        note = "Reported to the U.S. Department of Labor by this local's registered program."
        trend = l.get("intake_trend")
        if trend:
            direction = "up" if trend["pct_change"] > 0 else "down" if trend["pct_change"] < 0 else "unchanged"
            change = f'{direction} {abs(trend["pct_change"])}%' if direction != "unchanged" else "unchanged"
            note += f' Took {trend["fy2025"]:,} apprentices in FY2025 ({change} since FY2022).'
        return f'{val}<span>{esc(label)}</span><small>{note}</small>', "cell"
    # estimated
    val = f'<b>about {intake["value"]:,}</b>'
    label = "Estimated annual intake"
    if INTAKE_META.get("caveat") == "strong":
        note = ("Rough estimate based on DOL-registered programs and locals with similar "
                "membership. Intake varies widely between locals and year to year. "
                "Confirm with the JATC.")
    else:
        note = ("Estimated from DOL-registered programs and locals with similar membership. "
                "This local's own figure isn't in our data, and actual intake varies year to "
                "year. Confirm with the JATC.")
    return f'{val}<span>{esc(label)}</span><small>{note}</small>', "cell est"


def next_window_tile(l, today):
    """Tile 4: reuses the existing computed status / next_open_date -- no
    status logic recomputed here (compute_status.py is not touched)."""
    if not STATUS_DISPLAY or not l.get("status"):
        return NOT_PUBLISHED
    key, _ = display_state(l["status"], l.get("next_open"))
    if key == "open_now":
        return "Open now"
    if key == "always":
        return "Always accepting"
    if key == "opens_date":
        d = date.fromisoformat(l["next_open"])
        days = (d - today).days
        if days <= 0:
            return "Open now"
        return f'{fmt_date(l["next_open"])} <small>(in {days} day{"s" if days != 1 else ""})</small>'
    return NOT_PUBLISHED


def debug_stats_html(l):
    """Task 11: the old four tiles (population covered, jurisdiction
    population, ZIP count, national rank) are not candidate-facing -- they
    don't help someone decide whether/when to apply. Kept as a debug-only
    block gated on DEBUG_EVENTS instead of deleted outright."""
    return f"""<div class="grid" aria-hidden="true">
    <div class="cell"><b>{l['pop']:,}</b><span>People in jurisdiction (debug)</span>
      {f'<small>#{l["rank"]} of 245 nationally</small>' if l.get('rank') else ''}</div>
    <div class="cell"><b>{f"{l['members']:,}" if l.get('members') else '—'}</b><span>Union members (debug)</span>
      <small>{'DOL filing, FY2025' if l.get('members') else 'Not filed'}</small></div>
    <div class="cell"><b>{l['county_n']}</b><span>Counties covered (debug)</span></div>
    <div class="cell"><b>{l['zip_n']:,}</b><span>ZIP codes (debug)</span></div>
  </div>"""


def tiles_block_html(l, counties, today):
    jman_val, jman_note, jman_label = journeyman_tile(l, counties)
    appr_val = apprentice_tile(l)
    appr_note = apprentice_tile_note(l)
    window_val = next_window_tile(l, today)
    intake_html, intake_cls = intake_tile(l)
    req_bits = [v for v in (l.get("min_age"), l.get("min_edu")) if v and str(v).strip()]
    min_req = esc(", ".join(str(v) for v in req_bits)) if req_bits else "Not published"
    return f"""<div class="grid">
    <div class="cell{' est' if l.get('apprentice_wage_tier') == 'model_estimate' and WAGE_DISPLAY else ''}"><b>{appr_val}</b><span>{'Estimated apprentice starting pay' if l.get('apprentice_wage_tier') == 'model_estimate' and WAGE_DISPLAY else 'Verified apprentice starting pay range' if len(l.get('program_wages', [])) > 1 and WAGE_DISPLAY else 'Verified apprentice starting pay' if l.get('apprentice_wage_tier') == 'verified_program' and WAGE_DISPLAY else 'Apprentice wage'}</span>
      {f'<small>{appr_note}</small>' if appr_note else ''}</div>
    <div class="cell"><b>{jman_val}</b><span>{jman_label}</span>
      {f'<small>{jman_note}</small>' if jman_note else ''}</div>
    <div class="cell"><b>{window_val}</b><span>Next application window</span></div>
    <div class="{intake_cls}">{intake_html}</div>
  </div>
  <div class="snote">Verified rates link to official program sources. Estimated ranges are model projections and may differ from actual training center pay.</div>
  <div class="row"><span>Program length</span><b class="muted">Not published</b></div>
  <div class="row"><span>OJT hours</span><b class="muted">Not published</b></div>
  <div class="row"><span>Minimum requirements</span><b>{min_req}</b></div>"""


def wage_block_html(l):
    if not WAGE_DISPLAY:
        return ""
    w = l.get("wage")
    sections = []
    if w:
        rows = [
            f'<div class="row"><span>Base wage</span><b>{esc(wage_range(w.get("base_low"), w.get("base_high")))}</b></div>',
            f'<div class="row"><span>Fringe benefits</span><b>{esc(wage_range(w.get("fringe_low"), w.get("fringe_high")))}</b></div>',
            f'<div class="row"><span>Total package</span><b>{esc(wage_range(w.get("total_low"), w.get("total_high")))}</b></div>',
        ]
        source_name = f'U.S. Department of Labor Davis-Bacon prevailing wage determination {esc(w.get("wd_number", ""))}'
        source = (f'<a href="{esc(w.get("source", ""))}" target="_blank" rel="noopener">{source_name}</a>'
                  if w.get("source") else source_name)
        classification = " ".join(filter(None, [w.get("classification_text", ""), w.get("classification_code", "")]))
        classification_note = f' Classification: {esc(classification)}.' if classification else ""
        sections.append(f'<h2>Federal prevailing wage reference</h2>{"".join(rows)}'
                        f'<div class="snote">Effective {esc(wage_date(w))}. Source: {source}.{classification_note}</div>'
                        '<div class="snote">Davis-Bacon is the prevailing wage on federally funded construction; '
                        'where the rate is a union rate, it reflects the local IBEW agreement. Contractors on private work may pay differently.</div>')

    programs = l.get("program_wages", [])
    if programs:
        for program in programs:
            rows = ""
            for step in program["steps"]:
                pct = f' ({float(step["percent"]):g}%)' if step.get("percent") is not None else ''
                rows += (f'<div class="row"><span>{esc(step["period"])}{pct}</span>'
                         f'<b>${float(step["hourly_base"]):.2f}/hr</b></div>')
            if program["rate_kind"] == "starting_rate":
                rows = (f'<div class="row"><span>Published starting wage</span>'
                        f'<b>${float(program["starting_rate"]):.2f}/hr</b></div>')
            source = (f'<a href="{esc(program["source_url"])}" target="_blank" rel="noopener">'
                      f'{esc(program["source_label"])}</a>')
            if program.get("journeyman_base"):
                rows += (f'<div class="row"><span>Journeyman base</span>'
                         f'<b>${float(program["journeyman_base"]):.2f}/hr</b></div>')
            if program.get("effective_date"):
                date_note = f'effective {esc(program["effective_date"])}'
            elif program.get("as_of_date"):
                date_note = f'source says current as of {esc(program["as_of_date"])}'
            else:
                date_note = 'source does not state a wage effective date'
            sections.append(f'<h2>Apprentice pay: {esc(program["program_name"])}</h2>{rows}'
                            f'<div class="snote">Base hourly pay; {date_note}. '
                            f'Source: {source}. Verified {esc(program["verified_on"])}. Benefits are separate.</div>'
                            + (f'<div class="snote">{esc(program["rate_scope_note"])}</div>'
                               if program.get("rate_scope_note") else ''))
    else:
        official = (f' <a href="{esc(l["app_url"])}" target="_blank" rel="noopener">Check the training program</a>.'
                    if l.get("app_url") else "")
        estimate = l.get("apprentice_wage_estimate")
        if estimate:
            sections.append('<h2>Apprentice starting pay · regional model estimate</h2>'
                            f'<div class="row"><span>Estimated hourly base range</span><b>~${estimate["low"]}–${estimate["high"]}/hr</b></div>'
                            f'<div class="snote">{esc(estimate_evidence(estimate))}. '
                            'This is a broad geographic estimate, not a published wage for this local. Actual pay may fall outside this range. '
                            + ('No verified wage from this state was available for training. ' if estimate['state_peer_count'] == 0 else '')
                            + ('Inside jurisdiction mapping is unavailable, so the model uses state prices. ' if l.get('jurisdiction_unknown') else '')
                            + f'Research checked {esc(estimate["reviewed_on"])}. '
                            '<a href="../wage-estimates.html">Method and limitations</a>.' + official + '</div>')
        else:
            sections.append(f'<h2>Apprentice pay</h2><div class="snote">A current program-specific wage schedule has not been verified.{official}</div>')
    # Apprentice pay first: a candidate is deciding whether to spend five years
    # getting to the journeyman number, so what they earn on day one matters more.
    journeyman = sections[0] if w else ""
    apprentice = "".join(sections[1:] if w else sections)
    return apprentice + journeyman


def rapids_kpi_block_html(l):
    if not RAPIDS_DISPLAY or not l.get("rapids_kpi"):
        return ""
    k = l["rapids_kpi"]
    fy = f"FY{k['period_end'][:4]}" if k.get("period_start") and k.get("period_end") else ""
    fy_suffix = f" ({fy})" if fy else ""
    active = f"{k['active']:,}" if k.get("active") is not None else "—"
    new = f"{k['new']:,}" if k.get("new") is not None else "—"
    return (f'<h2>Apprenticeship program size</h2>'
            f'<div class="row"><span>Active apprentices{fy_suffix}</span><b>{active}</b></div>'
            f'<div class="row"><span>New apprentices{fy_suffix}</span><b>{new}</b></div>'
            f'<div class="snote">U.S. Department of Labor Registered Apprenticeship Partners Information Database '
            f'(RAPIDS), reporting period {esc(k.get("period_start", ""))} to {esc(k.get("period_end", ""))}. '
            'Reflects this local\'s registered JATC program under the general "Electrician" occupation code, '
            'which may include classifications beyond inside wireman.</div>'
            '<div class="snote">Not affiliated with or endorsed by IBEW. Figures are as registered with the '
            'U.S. Department of Labor, not a real-time headcount -- active apprentices includes everyone whose '
            'registration was open at any point in the period, which for a multi-year apprenticeship can mean '
            'several years of overlapping classes counted together.</div>')


def page_html(l, nearest):
    city, st, lu = l["city"], l["st"], l["lu"]
    title = f"IBEW Local {lu} Apprenticeship — {city}, {st} | Inside Wireman Program"
    if l.get("jurisdiction_unknown"):
        desc = (f"IBEW Local {lu} in {city}, {st} has an Inside Wireman training-center match. "
                "Its jurisdiction size is unavailable. Apprenticeship status, pay estimate, and how to apply.")
    else:
        county_word = "county" if l["county_n"] == 1 else "counties"
        desc = (f"IBEW Local {lu} in {city}, {st} serves {l['pop']:,} people across {l['county_n']} "
                f"{county_word}. Inside wireman apprenticeship status, requirements, and how to apply.")
    canonical = f"{SITE_BASE_URL}/locals/{l['slug']}"

    req = [("Minimum age", l.get("min_age")), ("Education", l.get("min_edu")), ("Aptitude test", l.get("aptitude"))]
    req = [(k, v) for k, v in req if v and str(v).strip()]

    counties = counties_full.get(l["id"], [])
    county_html = " &middot; ".join(esc(f'{c["name"]}, {c["state"]}') for c in counties) or '<span class="muted">Not on file</span>'

    zips = sorted(zips_full.get(l["id"], ()))
    zip_html = ", ".join(zips) if zips else '<span class="muted">Not on file</span>'

    website = l.get("website", "")
    website_href = website if website.startswith("http") else f"https://{website}" if website else ""
    lu_js = js_str(lu)

    nearby_html = "".join(
        f'<a href="{n["slug"]}.html">Local {n["lu"]} ({esc(n["city"])}, {n["st"]}) &middot; {n["dist"]:.0f} mi</a>'
        for n in nearest
    )

    reviewed_programs = l.get("program_applications") or l.get("program_wages") or []
    if reviewed_programs:
        program = reviewed_programs[0]
        jsonld = {
            "@context": "https://schema.org",
            "@type": "EducationalOccupationalProgram",
            "name": program["program_name"],
            "description": desc,
            "provider": {"@type": "Organization", "name": program["sponsor"],
                         "url": program["source_url"]},
            "occupationalCategory": "47-2111.00",
            "programType": "Apprenticeship",
            "url": program["source_url"],
        }
    else:
        jsonld = {"@context": "https://schema.org", "@type": "WebPage",
                  "name": title, "description": desc, "url": canonical}

    apply_rows = []
    if l.get("app_url"):
        apply_rows.append(f'<div class="row"><span>Application page</span><b><a href="{esc(l["app_url"])}" target="_blank" rel="noopener" '
                           f'onclick="track(\'outbound_local_click\',{{lu_number:{lu_js},link_type:\'apply\',surface:\'static\'}})">Official link &rarr;</a></b></div>')
    else:
        apply_rows.append('<div class="row"><span>Application page</span><b class="muted">Not published</b></div>')
    for app in l.get("program_applications", []):
        if app.get("flow_chart_url"):
            apply_rows.append(f'<div class="row"><span>{esc(app["program_name"])} flow chart</span>'
                              f'<b><a href="{esc(app["flow_chart_url"])}" target="_blank" rel="noopener">Official flow chart &rarr;</a></b></div>')
        if app.get("program_contact_email"):
            mail = esc(app["program_contact_email"])
            apply_rows.append(f'<div class="row"><span>Training program email</span><b><a href="mailto:{mail}">{mail}</a></b></div>')
    for center in l.get("training_centers", []):
        if center.get("website"):
            apply_rows.append(f'<div class="row"><span>Training center</span><b><a href="{esc(center["website"])}" '
                              f'target="_blank" rel="noopener">{esc(center["organization"])} &rarr;</a></b></div>')
    if website_href:
        apply_rows.append(f'<div class="row"><span>Local website</span><b><a href="{esc(website_href)}" target="_blank" rel="noopener" '
                           f'onclick="track(\'outbound_local_click\',{{lu_number:{lu_js},link_type:\'site\',surface:\'static\'}})">{esc(website)}</a></b></div>')
    if l.get("phone"):
        apply_rows.append(f'<div class="row"><span>Phone</span><b><a href="tel:{esc(re_digits(l["phone"]))}" '
                           f'onclick="track(\'outbound_local_click\',{{lu_number:{lu_js},link_type:\'phone\',surface:\'static\'}})">{esc(l["phone"])}</a></b></div>')
    if l.get("email"):
        label = "Union email" if l.get("program_applications") else "Email"
        apply_rows.append(f'<div class="row"><span>{label}</span><b><a href="mailto:{esc(l["email"])}">{esc(l["email"])}</a></b></div>')
    if l.get("meets"):
        apply_rows.append(f'<div class="row"><span>Meetings</span><b style="max-width:260px">{esc(l["meets"])}</b></div>')

    req_html = ""
    if req:
        req_html = "<h2>Requirements</h2>" + "".join(
            f'<div class="row"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in req)

    local_viewed_props = json.dumps({
        "lu_number": lu, "state": st, "status": l.get("status", ""), "surface": "static",
    })
    issue_context = json.dumps({"lu_number": lu, "city": city, "state": st, "slug": l.get("slug", "")})

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
{VERCEL_ANALYTICS_SNIPPET}
<!-- Google Analytics (GA4). This page doesn't render through the Next.js app's
     layout, so the gtag snippet is injected here directly. -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-S83RVT3S3B"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-S83RVT3S3B');
</script>
</head>
<body>
<script>
// Provider-agnostic on purpose: no vendor is chosen yet. Never pass PII in
// props -- the captured email must never reach track(). ZIP code/lu_number
// are fine.
const DEBUG_EVENTS = {'true' if DEBUG_EVENTS else 'false'};
function track(eventName, props){{
  try {{
    if (DEBUG_EVENTS) console.log('[track]', eventName, props || {{}});
    if (typeof gtag === 'function') gtag('event', eventName, props || {{}});
  }} catch (e) {{ /* tracking must never break the page */ }}
}}
track('local_viewed', {local_viewed_props});

// Task 13: same Supabase `leads` insert the finder's capture() does (same
// endpoint, same apikey/Authorization headers, same payload shape), plus
// lu_number so this lead is attributable to the local whose page sent it.
const SUPABASE_URL = {js_str(SUPABASE_URL)};
const SUPABASE_ANON_KEY = {js_str(SUPABASE_ANON_KEY)};
const REPORT_ISSUE_URL = {js_str(REPORT_ISSUE_URL)};
const CAPTURE_LEAD_URL = `${{SUPABASE_URL}}/functions/v1/capture-lead`;
const ISSUE_CONTEXT = {issue_context};
async function notifyMe(lu){{
  const emailEl = document.getElementById('nem-' + lu);
  const email = (emailEl && emailEl.value || '').trim();
  const website = (document.getElementById('nhp-' + lu)?.value || '').trim();
  const fine = document.getElementById('notifyfine-' + lu);
  if (!/^\\S+@\\S+\\.\\S+$/.test(email)){{ if (fine) fine.textContent = 'Enter a valid email address.'; return; }}
  const btn = document.querySelector('#notifybox-' + lu + ' button.btn');
  if (btn){{ btn.disabled = true; btn.textContent = 'Saving…'; }}
  try {{
    const res = await fetch(CAPTURE_LEAD_URL, {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'apikey': SUPABASE_ANON_KEY,
        'Authorization': `Bearer ${{SUPABASE_ANON_KEY}}`,
      }},
      body: JSON.stringify({{
        lu_number: lu, kind: 'alert', email, phone: null, website,
        clerk_user_id: (typeof Clerk !== 'undefined' && Clerk.user) ? Clerk.user.id : null,
      }}),
    }});
    if (!res.ok) throw new Error(`save failed: ${{res.status}}`);
    track('email_captured', {{lu_number: lu, surface: 'static'}});
    const box = document.getElementById('notifybox-' + lu);
    if (box) box.textContent = "Email alerts are launching soon. " + email + " is on the list for Local " + lu + ".";
  }} catch (err) {{
    if (btn){{ btn.disabled = false; btn.textContent = 'Notify me'; }}
    if (fine) fine.textContent = "Couldn't save that just now -- check your connection and try again.";
  }}
}}
function openIssueModal(){{
  const modal = document.getElementById('issue-modal');
  if (modal) modal.classList.add('on');
  const first = document.getElementById('issue-message');
  if (first) first.focus();
  track('report_issue_opened', {{lu_number: ISSUE_CONTEXT.lu_number, surface: 'static'}});
}}
function closeIssueModal(){{
  const modal = document.getElementById('issue-modal');
  if (modal) modal.classList.remove('on');
}}
async function submitIssue(){{
  const local = (document.getElementById('issue-local')?.value || '').trim();
  const place = (document.getElementById('issue-place')?.value || '').trim();
  const issueType = (document.getElementById('issue-type')?.value || '').trim();
  const message = (document.getElementById('issue-message')?.value || '').trim();
  const email = (document.getElementById('issue-email')?.value || '').trim();
  const fine = document.getElementById('issue-fine');
  const btn = document.getElementById('issue-submit');
  if (message.length < 5){{ if (fine) fine.textContent = 'Please tell us a little more about the issue.'; return; }}
  if (email && !/^\\S+@\\S+\\.\\S+$/.test(email)){{ if (fine) fine.textContent = 'Enter a valid email address, or leave it blank.'; return; }}
  if (btn){{ btn.disabled = true; btn.textContent = 'Sending…'; }}
  try {{
    const res = await fetch(REPORT_ISSUE_URL, {{
      method: 'POST', headers: {{'Content-Type':'application/json','apikey':SUPABASE_ANON_KEY,'Authorization':`Bearer ${{SUPABASE_ANON_KEY}}`}},
      body: JSON.stringify({{lu_number:local, local_location:place, issue_type:issueType, message,
        reporter_email:email || null, source_url:location.href, page_title:document.title, context:ISSUE_CONTEXT}}),
    }});
    if (!res.ok) throw new Error(`report failed: ${{res.status}}`);
    track('report_issue_submitted', {{lu_number: ISSUE_CONTEXT.lu_number, issue_type: issueType, surface: 'static'}});
    const card = document.getElementById('issue-card');
    if (card) card.innerHTML = '<div style="text-align:center;padding:14px 0"><div style="font-size:34px">&#9888;</div><h2>Report received</h2><p>Thanks — we’ll review the source and correct the page if needed.</p><button class="btn" onclick="closeIssueModal()">Close</button></div>';
  }} catch (err) {{
    if (btn){{ btn.disabled = false; btn.textContent = 'Send report'; }}
    if (fine) fine.textContent = 'We couldn’t send that just now. Please try again in a moment.';
  }}
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeIssueModal(); }});
</script>
<button class="report-fab" type="button" onclick="openIssueModal()">&#9888; Report an issue</button>
<div class="issue-modal" id="issue-modal" onclick="if(event.target===this)closeIssueModal()">
  <div class="issue-card" id="issue-card" role="dialog" aria-modal="true" aria-labelledby="issue-title">
    <span class="issue-close" onclick="closeIssueModal()" tabindex="0" role="button" aria-label="Close">&times;</span>
    <h2 id="issue-title">Report a data issue</h2>
    <p>Tell us what looks wrong and we’ll review the source and correct it manually.</p>
    <label for="issue-local">Local</label>
    <input id="issue-local" type="text" value="{esc(f'IBEW Local {lu}')}" aria-label="Local">
    <label for="issue-place">City and state</label>
    <input id="issue-place" type="text" value="{esc(f'{city}, {st}')}" aria-label="City and state">
    <label for="issue-type">What is wrong?</label>
    <select id="issue-type" aria-label="Issue type"><option>Wage data</option><option>Application status</option><option>Requirements</option><option>Contact information</option><option>Local match or jurisdiction</option><option>Other</option></select>
    <label for="issue-message">What should we fix?</label>
    <textarea id="issue-message" placeholder="Include the correct information or a link to the source." aria-label="Issue details"></textarea>
    <label for="issue-email">Your email (optional)</label>
    <input id="issue-email" type="email" placeholder="Only if you want a reply" aria-label="Your email address, optional">
    <button class="btn primary" id="issue-submit" type="button" onclick="submitIssue()">Send report</button>
    <div class="issue-fine" id="issue-fine">The current page and local context will be included automatically. You can edit the prefilled fields.</div>
  </div>
</div>
<div class="wrap">
  <div class="topnav"><a href="https://app.apprentable.org/resources/find-your-local?ref=locals-site">&larr; Back to the IBEW Apprenticeship Finder</a></div>
  <h1>IBEW Local {esc(lu)}</h1>
  <div class="sub">{esc(city)}, {esc(st)}{f' &middot; {esc(l["jatc"])}' if l.get("jatc") else ''}</div>

  {status_block_html(l)}

  {cta_block_html(l)}

  {tiles_block_html(l, counties, TODAY)}

  {debug_stats_html(l) if DEBUG_EVENTS else ''}

  {wage_block_html(l)}

{rapids_kpi_block_html(l)}

  {req_html}

  <h2>Apply</h2>
  {''.join(apply_rows)}

  <h2>{'Jurisdiction counties unavailable' if l.get('jurisdiction_unknown') else f"Counties served ({l['county_n']})"}</h2>
  <div class="counties">{county_html}</div>

  <h2>{'Jurisdiction ZIP codes unavailable' if l.get('jurisdiction_unknown') else f"ZIP codes served ({l['zip_n']:,})"}</h2>
  <details><summary>Show all ZIP codes</summary><div class="zips">{esc(zip_html)}</div></details>

  <h2>Nearby locals</h2>
  <div class="nearby">{nearby_html or '<span class="muted">None on file</span>'}</div>

  <footer>Page built {generated}. This is the build date, not a verification date &mdash;
  it does not mean every value on this page was re-checked that day. Application status and requirements come from official
  training-program or local websites and can change without notice &mdash; confirm with the program before relying
  on this page. &copy; IBEW Apprenticeship Finder.
  <p>This is an independent, unofficial resource. It is not affiliated with, endorsed by, or
  sponsored by the International Brotherhood of Electrical Workers (IBEW), the National Electrical
  Contractors Association (NECA), IBEW Local {esc(lu)}, or any other local union or Joint
  Apprenticeship and Training Committee (JATC).</p></footer>
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
    path = f"{OUT_DIR}/locals/{slug}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    pages_written.append((slug, os.path.getsize(path)))

# ---- Crawlable directory: a plain HTML path from the finder to every local ---
by_state = {}
for l in locals_:
    by_state.setdefault(l["st"], []).append(l)
state_nav = " ".join(f'<a href="#state-{esc(st)}">{esc(st)}</a>' for st in sorted(by_state))
state_sections = []
for st, entries in sorted(by_state.items()):
    links = "\n".join(
        f'<li><a href="locals/{esc(l["slug"])}.html">IBEW Local {esc(l["lu"])} '
        f'&mdash; {esc(l["city"])}, {esc(st)}</a></li>'
        for l in sorted(entries, key=lambda item: (item["city"].casefold(), int(item["lu"])))
    )
    state_sections.append(f'<section id="state-{esc(st)}"><h2>{esc(st)}</h2><ul>{links}</ul></section>')
directory_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>All IBEW Local Apprenticeship Pages | Apprentable</title>
<meta name="description" content="Browse {len(locals_)} IBEW local apprenticeship pages by state, with application status, requirements, wages, and official program links.">
<link rel="canonical" href="{SITE_BASE_URL}/all-locals.html">
<link rel="stylesheet" href="local.css">
{VERCEL_ANALYTICS_SNIPPET}
<style>
.directory {{max-width:920px}}
.state-nav {{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0}}
.state-nav a {{border:1px solid var(--line);border-radius:6px;padding:4px 7px}}
.directory section {{margin:24px 0}}
.directory ul {{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 22px;list-style:none;padding:0}}
.directory li a {{display:block;padding:7px 0;border-bottom:1px solid var(--line)}}
</style>
</head>
<body>
<main class="wrap directory">
<div class="topnav"><a href="https://app.apprentable.org/resources/find-your-local?ref=locals-site">&larr; Find Your Local by ZIP or City</a></div>
<h1>All IBEW Local Apprenticeship Pages</h1>
<p>Browse {len(locals_)} inside wireman local profiles by state. Each page includes application details, requirements, and available wage information.</p>
<nav class="state-nav" aria-label="Jump to state">{state_nav}</nav>
{''.join(state_sections)}
</main>
</body>
</html>
"""
with open(f"{OUT_DIR}/all-locals.html", "w", encoding="utf-8") as f:
    f.write(directory_html)

# The estimate explanation is a first-class public page linked beside every
# modeled range. Build it from the same calibration metadata as the values.
with open("out/apprentice_wage_estimates.json", encoding="utf-8") as f:
    wage_estimate_meta = json.load(f)
method_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>How apprentice wage estimates work | Apprentable</title>
<meta name="description" content="How Apprentable estimates broad apprentice starting-pay ranges when an official training center does not publish a current wage.">
<link rel="canonical" href="{SITE_BASE_URL}/wage-estimates.html"><link rel="stylesheet" href="local.css">
</head><body><main class="wrap directory">
<div class="topnav"><a href="https://app.apprentable.org/resources/find-your-local?ref=locals-site">&larr; Find Your Local</a></div>
<h1>How Apprentice Wage Estimates Work</h1>
<p>For {len(wage_estimate_meta['estimates'])} Inside Wireman locals without a verified current starting wage, we show a broad <strong>regional model estimate</strong>. It is not a wage quoted by a training center. Each local page explains why its pay remains unverified, including outdated sources, uncertain program matches, unavailable sites, and unconfirmed centers.</p>
<h2>What the Range Means</h2>
<p>We trained on {wage_estimate_meta['training_locals']} locals with one verified Inside Wireman wage schedule each. The model adjusts those rates using 2024 regional cost-of-living data and, where available, verified wages from the same state. It weights metro areas across each local's Inside jurisdiction, using a state price index where county mapping is unavailable. The displayed range extends about ${wage_estimate_meta['half_width_dollars']}/hr on either side of the prediction, rounded outward to whole dollars.</p>
<p>In a harder test that withheld each state in turn, 90% of verified-local errors were within ${wage_estimate_meta['holdout_90th_percentile_error']:.2f}/hr. This is a historical test on locals that publish wages, <strong>not a 90% guarantee</strong> for a local that does not. Actual pay can fall outside the displayed range.</p>
<p>Some estimated locals had no verified training wage from their state. For those, the model relies on regional price data and verified wages elsewhere; the local page says so.</p>
<h2>What It Leaves Out</h2>
<p>Cost of living cannot reveal a local's negotiated agreement, wage zone, starting period, or future raise. The published wages used for training have different effective dates. Two locals with multiple wage zones were left out of model training rather than averaged together; their published rates are displayed as verified ranges. Benefits and journeyman rates are excluded. Where the official source is stale, ambiguous, or unavailable, the model range has no direct program wage evidence. A verified current rate always takes priority over a model estimate.</p>
<h2>Sources</h2>
<p>The wage inputs are <a href="all-locals.html">individually linked official JATC or local program schedules</a>. Geography uses <a href="https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area">U.S. BEA regional price parities</a> and <a href="https://www.census.gov/programs-surveys/metro-micro/about/delineation-files.html">U.S. Census metro definitions</a>. Model checked {esc(wage_estimate_meta['generated_on'])}. Check the linked training center for its actual current pay before relying on an estimate.</p>
</main></body></html>
"""
with open(f"{OUT_DIR}/wage-estimates.html", "w", encoding="utf-8") as f:
    f.write(method_html)

# ---- site/index.html: the branded finder, lean build -------------------------
# ZIP/city indexes fetched from site/data/*.json on first search instead of
# being inlined -- keeps the hosted entry page light. ibew_finder.html (built
# separately by `python build_page.py --single`) stays fully inlined for
# file://.
import build_brand_preview
build_brand_preview.build(production=True, show_confidence=SHOW_CONFIDENCE,
                          status_display=STATUS_DISPLAY, wage_display=WAGE_DISPLAY,
                          rapids_display=RAPIDS_DISPLAY, debug_events=DEBUG_EVENTS)

# ---- sitemap.xml + robots.txt --------------------------------------------------
urls = [f"{SITE_BASE_URL}/", f"{SITE_BASE_URL}/all-locals.html", f"{SITE_BASE_URL}/wage-estimates.html"] + [
    f"{SITE_BASE_URL}/locals/{l['slug']}" for l in locals_
]
sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for u in urls:
    sitemap.append(f"  <url><loc>{u}</loc><lastmod>{generated}</lastmod></url>")
sitemap.append("</urlset>")
with open(f"{OUT_DIR}/sitemap.xml", "w", encoding="utf-8") as f:
    f.write("\n".join(sitemap) + "\n")

with open(f"{OUT_DIR}/robots.txt", "w", encoding="utf-8") as f:
    f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE_BASE_URL}/sitemap.xml\n")

sizes = sorted(sz for _, sz in pages_written)
print(f"local pages written: {len(pages_written)}")
print(f"page size: min {sizes[0]/1024:.1f} KB, median {sizes[len(sizes)//2]/1024:.1f} KB, "
      f"max {sizes[-1]/1024:.1f} KB")
print(f"{OUT_DIR}/index.html: {os.path.getsize(OUT_DIR + '/index.html')/1024:.0f} KB")
print(f"unique slugs: {len(slugs_seen)}")

# ---- build-time internal link check (task 3) -----------------------------------
# This is the last step of the documented build order, so every artifact the
# other steps produced (ibew_finder.html, site/index.html, site/locals/*.html)
# exists on disk by the time this runs. A broken internal link fails the build.
import check_links
check_links.main()
