"""Task 1 diagnostic: run the full sweep twice, ~10 minutes apart, and diff
the CURRENT normalizer's output (monitor.normalize_visible_text's normalized
text, unchanged) between the two runs.

Anything that differs across two runs this close together is, by
definition, noise -- no union hall edits its page twice in ten minutes.
This does not touch out/monitor_state.json; it's a standalone diagnostic
so it can't corrupt real change history while measuring the false-positive
rate.

Split into two invocations (--run a / --run b) rather than one process
holding a 10-minute internal sleep, so each half finishes well within a
single sweep's own runtime and neither depends on a long-lived background
process surviving unattended.

  python monitor_noise_audit.py --run a      # fetch + checkpoint to JSON
  ... wait ~10 minutes ...
  python monitor_noise_audit.py --run b      # fetch + diff against checkpoint, write CSV

Writes out/monitor_noise_audit.csv: local_union_id, lu_number, url,
hash_run_a, hash_run_b, differs, bytes_run_a, bytes_run_b,
first_diff_offset, diff_sample_a, diff_sample_b.
"""
import argparse
import csv
import json
import time

import monitor

OUT_PATH = "out/monitor_noise_audit.csv"
CHECKPOINT_PATH = "out/monitor_noise_audit_run_a.json"
SAMPLE_RADIUS = 100  # 200 chars total, centered on the first difference


def normalize(text):
    if text is None:
        return None
    return monitor.normalize_visible_text(text)


def sweep(urls):
    """Fetch every URL once; return dict url -> normalized_text_or_None."""
    results = {}
    for i, url in enumerate(urls):
        text, status, err = monitor.fetch_with_retry(url)
        results[url] = normalize(text)
        if (i + 1) % 25 == 0 or i == len(urls) - 1:
            print(f"  fetched {i + 1}/{len(urls)}", flush=True)
        if i < len(urls) - 1:
            time.sleep(monitor.SLEEP_BETWEEN)
    return results


def first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def sample_around(text, offset, radius=SAMPLE_RADIUS):
    if offset is None or text is None:
        return ""
    start = max(0, offset - radius)
    end = min(len(text), offset + radius)
    return text[start:end]


def run_a():
    url_to_locals = monitor.load_url_to_locals()
    urls = list(url_to_locals.keys())
    print(f"Run A: fetching {len(urls)} distinct URLs...", flush=True)
    normalized = sweep(urls)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f)
    print(f"Run A done. Checkpoint written to {CHECKPOINT_PATH}.", flush=True)


def run_b():
    lu_by_local = {}
    with open("out/targets_with_population.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lu_by_local[r["local_union_id"]] = r["lu_number"]

    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        run_a_norm = json.load(f)

    url_to_locals = monitor.load_url_to_locals()
    urls = list(url_to_locals.keys())
    print(f"Run B: fetching {len(urls)} distinct URLs...", flush=True)
    run_b_norm = sweep(urls)
    print("Run B done. Building diff report...", flush=True)

    rows = []
    for url in urls:
        text_a = run_a_norm.get(url)
        text_b = run_b_norm.get(url)
        hash_a = monitor.hash_text(text_a) if text_a is not None else ""
        hash_b = monitor.hash_text(text_b) if text_b is not None else ""
        differs = bool(text_a is not None and text_b is not None and hash_a != hash_b)
        offset = first_diff(text_a, text_b) if (text_a is not None and text_b is not None) else None
        for local_id in url_to_locals[url]:
            rows.append({
                "local_union_id": local_id,
                "lu_number": lu_by_local.get(local_id, ""),
                "url": url,
                "hash_run_a": hash_a,
                "hash_run_b": hash_b,
                "differs": differs,
                "bytes_run_a": len(text_a.encode("utf-8")) if text_a is not None else "",
                "bytes_run_b": len(text_b.encode("utf-8")) if text_b is not None else "",
                "first_diff_offset": offset if offset is not None else "",
                "diff_sample_a": sample_around(text_a, offset),
                "diff_sample_b": sample_around(text_b, offset),
            })

    rows.sort(key=lambda r: (not r["differs"], r["lu_number"]))
    fields = ["local_union_id", "lu_number", "url", "hash_run_a", "hash_run_b", "differs",
              "bytes_run_a", "bytes_run_b", "first_diff_offset", "diff_sample_a", "diff_sample_b"]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    differing = sum(1 for r in rows if r["differs"])
    print(f"Wrote {OUT_PATH}: {total} locals, {differing} differ over the gap "
          f"({100.0 * differing / total:.1f}% false-positive rate)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", choices=["a", "b"], required=True)
    args = ap.parse_args()
    if args.run == "a":
        run_a()
    else:
        run_b()


if __name__ == "__main__":
    main()
