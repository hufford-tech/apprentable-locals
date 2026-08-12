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
"""
import argparse
import json
import os

FIRST_PAINT_KEYS = {"generated", "locals"}


def _escape_for_script_tag(json_text):
    # guard against breaking out of the <script type="application/json"> block
    return json_text.replace("</", "<\\/")


def build_single(out_path="ibew_finder.html", template_path="page_template.html",
                  data_path="out/frontend_data.json"):
    tpl = open(template_path, encoding="utf-8").read()
    data = open(data_path, encoding="utf-8").read()
    html = tpl.replace("__DATA__", _escape_for_script_tag(data))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.getsize(out_path)


def build_lean(out_path="site/index.html", template_path="page_template.html",
                data_path="out/frontend_data.json", data_dir="site/data"):
    with open(data_path, encoding="utf-8") as f:
        bundle = json.load(f)

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

    if args.single:
        size = build_single()
        print(f"ibew_finder.html written: {size/1024:.0f} KB")
    if args.lean:
        sizes = build_lean()
        for name, sz in sizes.items():
            print(f"site/{name} written: {sz/1024:.0f} KB")
