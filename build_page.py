"""Build the finder page from page_template.html + out/frontend_data.json
(frontend task 8).

--single (default): inline the full payload into ibew_finder.html at the repo
root. Works from file:// with no server -- keep this working, it's the file
that gets opened directly day to day.

--lean: split the bundle. Inline only what first paint needs (the 245 locals'
map+card fields); move the ZIP and city indexes to site/data/zips.json and
site/data/cities.json, fetched on first search. Writes site/index.html.

Both modes read the same out/frontend_data.json -- run build_frontend_data.py
first. Zero network.

show_confidence / status_display (task 9): when a flag is off this doesn't
just gate rendering at runtime -- the JS is source text sitting in the file
either way, so a runtime-only toggle would still leave the literal strings
grep-able. When a flag is off this also (a) strips the corresponding fields
from the embedded JSON payload so no confidence/status value ships at all,
and (b) deletes the dead label/confidence-badge JS literals from the
template text for that build. The two named constants remain the single
switch a real deploy flips; this function is the one place that has to know
about the flag beyond that.
"""
import argparse
import copy
import json
import os
import re
from pathlib import Path

from map_outlines import outline_paths

FIRST_PAINT_KEYS = {"generated", "locals", "intake_meta", "zip_count", "build"}


def _escape_for_script_tag(json_text):
    # guard against breaking out of the <script type="application/json"> block
    return json_text.replace("</", "<\\/")


def _redact_locals(bundle, show_confidence, status_display, wage_display=True, rapids_display=True):
    bundle = copy.deepcopy(bundle)
    for l in bundle.get("locals", []):
        if not show_confidence:
            l["conf"] = ""
            l["quote"] = ""
            l["src"] = ""
        if not status_display:
            l["status"] = ""
            l["pattern"] = ""
            l["next_open"] = ""
            l["next_close"] = ""
        if not wage_display:
            l.pop("wage", None)
            l.pop("program_wages", None)
            l.pop("apprentice_wage_estimate", None)
        if not rapids_display:
            l.pop("rapids_kpi", None)
            l.pop("intake", None)
    if not show_confidence:
        # zip_multi's "cf" is the ZIP-to-local match confidence (a different
        # concept from application-status confidence), but it's still a
        # confidence value -- redact it under the same flag rather than leave
        # a loophole.
        for cands in bundle.get("zip_multi", {}).values():
            for c in cands:
                c["cf"] = ""
    return bundle


def _load_finder_core(show_confidence, status_display, core_path="site/js/finder-core.js"):
    # Task 10: LABEL/NOTE/CONF_LABEL live here, not in the inline template --
    # strip the dictionaries a disabled flag would otherwise leak as dead JS
    # source text (see the module docstring: a runtime-only toggle isn't
    # enough for the grep check in task 9).
    core = open(core_path, encoding="utf-8").read()
    if not status_display:
        core = re.sub(r"const LABEL = \{.*?\};", "const LABEL = {};", core, flags=re.S)
        core = re.sub(r"const NOTE = \{.*?\};", "const NOTE = {};", core, flags=re.S)
    if not show_confidence:
        # The confidence API is useful in the testable source module, but it
        # is dead code in a confidence-off build.  Remove its user-facing
        # vocabulary as well as the badge branch in the template.
        core = re.sub(r"const CONF_LABEL = \{.*?\};", "const CL = {};", core, flags=re.S)
        core = core.replace("CONF_LABEL", "CL").replace("confidenceLabel", "cl")
    return core


def _apply_flags(tpl, show_confidence, status_display, wage_display, rapids_display=True, debug_events=False):
    tpl = tpl.replace("__MAP_OUTLINES__", json.dumps(outline_paths(), separators=(",", ":")))
    license_text = (Path(__file__).resolve().parent / "raw/maps/LICENSE-us-atlas.txt").read_text(encoding="utf-8")
    tpl = tpl.replace("__MAP_LICENSE__", license_text.strip())
    tpl = tpl.replace("const SHOW_CONFIDENCE = false;",
                       f"const SHOW_CONFIDENCE = {'true' if show_confidence else 'false'};")
    tpl = tpl.replace("const STATUS_DISPLAY  = true;",
                       f"const STATUS_DISPLAY  = {'true' if status_display else 'false'};")
    tpl = tpl.replace("const WAGE_DISPLAY    = true;",
                       f"const WAGE_DISPLAY    = {'true' if wage_display else 'false'};")
    tpl = tpl.replace("const RAPIDS_DISPLAY  = true;",
                       f"const RAPIDS_DISPLAY  = {'true' if rapids_display else 'false'};")
    tpl = tpl.replace("const DEBUG_EVENTS    = false;",
                       f"const DEBUG_EVENTS    = {'true' if debug_events else 'false'};")
    if not wage_display:
        tpl = re.sub(r"/\* WAGE_BLOCK_START \*/.*?/\* WAGE_BLOCK_END \*/", "", tpl, flags=re.S)
    if not rapids_display:
        tpl = re.sub(r"/\* RAPIDS_BLOCK_START \*/.*?/\* RAPIDS_BLOCK_END \*/", "", tpl, flags=re.S)
    tpl = tpl.replace("__FINDER_CORE__", _load_finder_core(show_confidence, status_display))
    if not show_confidence or not status_display:
        # the source-level CONFIG comment documents both flags using the words
        # "confidence"/status label examples -- strip it for a build with
        # either flag off so a grep for those words has nothing to find here.
        tpl = re.sub(
            r"/\* =+\s*\n\s*CONFIG.*?=+ \*/",
            "/* build-time flags, see build_page.py */",
            tpl, flags=re.S,
        )
    if not show_confidence:
        # only ever rendered when SHOW_CONFIDENCE is true; delete the dead literals.
        tpl = tpl.replace(
            '`<span class="sconf">${l.conf} confidence</span>`',
            "''",
        )
        tpl = tpl.replace(
            "${SHOW_CONFIDENCE?`<div><span>ZIP confidence</span><b>${confidenceLabel(c.cf)}</b></div>`:''}",
            "''",
        )
    if not status_display:
        # statusHTML() returns a static "Check with the local" string and
        # never reaches this line when STATUS_DISPLAY is false, but the JS
        # source text -- including the "Open now, closes" copy -- still ships
        # in the file either way. Found leaking during task-11
        # re-verification; same category of fix as the sconf/LABEL/NOTE ones.
        tpl = tpl.replace(
            "${l.status==='open' ? 'Open now, closes ' : 'Closes '}${fmtDate(l.next_close)}.",
            "''",
        )
    return tpl


def build_single(out_path="ibew_finder.html", template_path="page_template.html",
                 data_path="out/frontend_data.json", show_confidence=False, status_display=True,
                 wage_display=True, rapids_display=True, debug_events=False):
    tpl = open(template_path, encoding="utf-8").read()
    tpl = _apply_flags(tpl, show_confidence, status_display, wage_display, rapids_display, debug_events)
    # out_path sits at the repo root; profile pages live under site/locals/
    tpl = tpl.replace("__PROFILE_BASE__", "site/locals/")
    tpl = tpl.replace("__DIRECTORY_HREF__", "site/all-locals.html")
    tpl = tpl.replace("__WAGE_METHOD_URL__", "site/wage-estimates.html")
    with open(data_path, encoding="utf-8") as f:
        bundle = json.load(f)
    bundle = _redact_locals(bundle, show_confidence, status_display, wage_display, rapids_display)
    data = json.dumps(bundle, separators=(",", ":"))
    html = tpl.replace("__DATA__", _escape_for_script_tag(data))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.getsize(out_path)


def build_lean(out_path="site/index.html", template_path="page_template.html",
                data_path="out/frontend_data.json", data_dir="site/data",
                show_confidence=False, status_display=True, wage_display=True, rapids_display=True,
                debug_events=False):
    with open(data_path, encoding="utf-8") as f:
        bundle = json.load(f)
    bundle = _redact_locals(bundle, show_confidence, status_display, wage_display, rapids_display)

    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "zips.json"), "w", encoding="utf-8") as f:
        json.dump(bundle["zips"], f, separators=(",", ":"))
    with open(os.path.join(data_dir, "zip_multi.json"), "w", encoding="utf-8") as f:
        json.dump(bundle["zip_multi"], f, separators=(",", ":"))
    with open(os.path.join(data_dir, "cities.json"), "w", encoding="utf-8") as f:
        json.dump(bundle["cities"], f, separators=(",", ":"))

    first_paint = {k: v for k, v in bundle.items() if k in FIRST_PAINT_KEYS}
    first_paint["zips"] = {}
    first_paint["zip_multi"] = {}
    first_paint["cities"] = {}
    first_paint["lean"] = True

    tpl = open(template_path, encoding="utf-8").read()
    tpl = _apply_flags(tpl, show_confidence, status_display, wage_display, rapids_display, debug_events)
    # out_path sits inside site/; profile pages live under site/locals/, a sibling dir
    tpl = tpl.replace("__PROFILE_BASE__", "locals/")
    tpl = tpl.replace("__DIRECTORY_HREF__", "all-locals.html")
    tpl = tpl.replace("__WAGE_METHOD_URL__", "wage-estimates.html")
    payload = _escape_for_script_tag(json.dumps(first_paint, separators=(",", ":")))
    html = tpl.replace("__DATA__", payload)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    sizes = {
        "index.html": os.path.getsize(out_path),
        "data/zips.json": os.path.getsize(os.path.join(data_dir, "zips.json")),
        "data/zip_multi.json": os.path.getsize(os.path.join(data_dir, "zip_multi.json")),
        "data/cities.json": os.path.getsize(os.path.join(data_dir, "cities.json")),
    }
    return sizes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", action="store_true")
    ap.add_argument("--lean", action="store_true")
    args = ap.parse_args()
    if not args.single and not args.lean:
        args.single = True  # default: preserve prior behavior
    show_confidence = os.environ.get("SHOW_CONFIDENCE", "false").lower() == "true"
    status_display = os.environ.get("STATUS_DISPLAY", "true").lower() != "false"
    wage_display = os.environ.get("WAGE_DISPLAY", "true").lower() != "false"
    # Refreshed estimate model validates at 36.4% MdAPE (35-60% band) --
    # see rapids_intake_estimate.py / README.
    rapids_display = os.environ.get("RAPIDS_DISPLAY", "true").lower() != "false"
    debug_events = os.environ.get("DEBUG_EVENTS", "false").lower() == "true"

    if args.single:
        size = build_single(show_confidence=show_confidence, status_display=status_display,
                             wage_display=wage_display, rapids_display=rapids_display,
                             debug_events=debug_events)
        print(f"ibew_finder.html written: {size/1024:.0f} KB")
    if args.lean:
        sizes = build_lean(show_confidence=show_confidence, status_display=status_display,
                            wage_display=wage_display, rapids_display=rapids_display,
                            debug_events=debug_events)
        for name, sz in sizes.items():
            print(f"site/{name} written: {sz/1024:.0f} KB")
