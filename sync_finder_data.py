"""Export the built finder bundle into the Apprentable app's public assets.

Run after ``python build_frontend_data.py`` in the ibew checkout. The three
search indexes come from that build output, not from possibly stale site/data.
"""

import argparse
import json
import sys
from pathlib import Path


def write_json(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--app-root", type=Path, default=Path.cwd().parent / "ibew-prep")
    args = parser.parse_args()
    source = args.source_root.resolve()
    target = args.app_root.resolve() / "public" / "data" / "locals"
    bundle_path = source / "out" / "frontend_data.json"
    if not bundle_path.is_file():
        parser.error(f"missing {bundle_path}; run build_frontend_data.py first")
    if not (args.app_root / "app" / "layout.tsx").is_file():
        parser.error(f"{args.app_root} does not look like the Apprentable app")

    sys.path.insert(0, str(source))
    from build_page import FIRST_PAINT_KEYS, _redact_locals  # pylint: disable=import-outside-toplevel
    from map_outlines import outline_paths  # pylint: disable=import-outside-toplevel

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle = _redact_locals(bundle, False, True, True, True)
    locals_payload = {key: value for key, value in bundle.items() if key in FIRST_PAINT_KEYS}
    indexes = {key: bundle[key] for key in ("zips", "zip_multi", "cities")}
    local_count = len(locals_payload["locals"])
    if not local_count or not indexes["zips"] or not indexes["cities"]:
        parser.error(f"unexpected finder data: {local_count} locals, {len(indexes['zips'])} ZIPs")
    for zip_code, hits in indexes["zips"].items():
        if any(not isinstance(index, int) or index < 0 or index >= local_count for index in hits):
            parser.error(f"invalid local index in ZIP {zip_code}")

    target.mkdir(parents=True, exist_ok=True)
    assets = {
        "locals.json": locals_payload,
        "map_outlines.json": outline_paths(),
        "zips.json": indexes["zips"],
        "zip_multi.json": indexes["zip_multi"],
        "cities.json": indexes["cities"],
    }
    total = 0
    for name, value in assets.items():
        size = write_json(target / name, value)
        total += size
        print(f"{name}: {size:,} bytes")
    print(f"Total: {total:,} bytes -> {target}")


if __name__ == "__main__":
    main()
