"""Audit out/*.csv for literal Python-stringified values ("False", "True",
"None", "nan") sitting in fields where a URL, name, or date belongs.

Report only -- does not modify any source CSV or the build layer.
"""
from __future__ import annotations

import csv
import glob
import os

csv.field_size_limit(10_000_000)

OUT = "out/string_leak_audit.csv"
LITERALS = {"False", "True", "None", "nan"}
LU_COLUMN_CANDIDATES = ("lu_number", "local_union_id", "lu", "charter_number")


def find_lu_column(fieldnames):
    for cand in LU_COLUMN_CANDIDATES:
        if cand in fieldnames:
            return cand
    return None


def main():
    rows_out = []
    for path in sorted(glob.glob("out/*.csv")):
        if os.path.basename(path) in ("string_leak_audit.csv", "application_url_candidates.csv"):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                lu_col = find_lu_column(fieldnames)
                hits = {}  # (column, literal) -> {count, samples}
                for row in reader:
                    for col, val in row.items():
                        if col is None or not isinstance(val, str):
                            continue
                        if val in LITERALS:
                            key = (col, val)
                            bucket = hits.setdefault(key, {"count": 0, "samples": []})
                            bucket["count"] += 1
                            if len(bucket["samples"]) < 5 and lu_col:
                                bucket["samples"].append(row.get(lu_col, ""))
        except (OSError, csv.Error) as exc:
            print(f"skip {path}: {exc}")
            continue
        for (col, literal), bucket in sorted(hits.items()):
            rows_out.append({
                "file": path.replace("\\", "/"),
                "column": col,
                "literal": literal,
                "row_count": bucket["count"],
                "sample_lu": ";".join(bucket["samples"]),
            })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        fields = ["file", "column", "literal", "row_count", "sample_lu"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    total = sum(r["row_count"] for r in rows_out)
    print(f"leak rows found: {len(rows_out)} (file,column,literal) groups; {total} total cells")
    for r in rows_out:
        print(f"  {r['file']} :: {r['column']} = {r['literal']!r} x{r['row_count']} (e.g. LU {r['sample_lu']})")


if __name__ == "__main__":
    main()
