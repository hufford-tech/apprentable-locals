"""Bounded, cache-first SAM.gov Davis-Bacon pull.

SAM's public UI did not expose usable state query parameters during the access
check, so this uses bounded sequential history probes as specified in the task.
Every request is counted, paced, and recorded.  The parser itself never calls
the network.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

from parse_davisbacon import parse_cache


CACHE = Path("raw/davisbacon")
MANIFEST = CACHE / "pull_manifest.json"
VALIDATION_MANIFEST = CACHE / "validation_manifest.json"
COVERAGE_MANIFEST = CACHE / "coverage_manifest.json"
GAP_COVERAGE_MANIFEST = CACHE / "gap_coverage_manifest.json"
ROLLOVER_CROSSWALK = CACHE / "rollover_crosswalk_2026.pdf"
BLOCKERS = Path("out/davisbacon_blockers.csv")
BASE = "https://sam.gov/api/prod/wdol/v1/wd"
USER_AGENT = "IBEW Davis-Bacon research (public-rate cache; contact@example.invalid)"


def write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def run_curl(url: str) -> tuple[int, bytes, str]:
    """One polite GET.  Caller owns the one-second interval and cap."""
    p = subprocess.run(
        ["curl.exe", "-L", "--connect-timeout", "20", "--max-time", "45", "-A", USER_AGENT,
         "-sS", "-w", "\n%{http_code}", url],
        capture_output=True,
        check=False,
    )
    raw = p.stdout
    body, sep, status = raw.rpartition(b"\n")
    try:
        code = int(status.decode("ascii", "ignore")) if sep else 0
    except ValueError:
        code = 0
    return code, body, p.stderr.decode("utf-8", "replace")


def target_states() -> list[str]:
    targets = load_csv("out/targets_with_population.csv")
    inside = {r["local_union_id"] for r in load_csv("out/jurisdictions.csv") if (r.get("jurisdiction_type") or "").upper() == "I"}
    eligible = [r for r in targets if r["local_union_id"] in inside]
    top = sorted(eligible, key=lambda r: -float(r.get("population_current_served_inside") or 0))[:100]
    top_count = Counter(r.get("charter_state", "") for r in top)
    population = defaultdict(float)
    for r in eligible:
        population[r.get("charter_state", "")] += float(r.get("population_current_served_inside") or 0)
    return [state for state, _ in sorted(top_count.items(), key=lambda x: (-x[1], -population[x[0]], x[0])) if state]


def load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"method": "bounded_sequential_history_probe", "requests": 0, "pages_cached": 0,
            "failures": [], "states": []}


def save_manifest(manifest: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def fetch_direct(wd: str, revision: int, manifest_path: Path = VALIDATION_MANIFEST, request_cap: int = 60) -> dict:
    """Fetch one known public determination without an inventory probe.

    Used for the round-three validation set.  It records its own bounded
    request budget so validation work cannot silently consume coverage budget.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except json.JSONDecodeError:
        manifest = {}
    manifest.setdefault("method", "known_url_direct_fetch")
    manifest.setdefault("requests", 0)
    manifest.setdefault("pages_cached", 0)
    manifest.setdefault("failures", [])
    manifest.setdefault("documents", [])
    if manifest["requests"] >= request_cap:
        return {"wd": wd, "revision": revision, "status": 0, "reason": "request_cap"}
    path = CACHE / f"{wd}_{revision}.json"
    if path.exists():
        return {"wd": wd, "revision": revision, "status": 200, "reason": "already_cached", "path": str(path)}
    if manifest["requests"]:
        time.sleep(1)
    manifest["requests"] += 1
    status, body, stderr = run_curl(f"{BASE}/{wd}/{revision}")
    result = {"wd": wd, "revision": revision, "status": status, "reason": ""}
    if status == 200:
        try:
            document = json.loads(body.decode("utf-8"))
            path.write_text(json.dumps(document), encoding="utf-8")
            manifest["pages_cached"] += 1
            manifest["documents"].append(f"{wd}/{revision}")
            result["path"] = str(path)
        except json.JSONDecodeError:
            result["reason"] = "invalid_json"
    else:
        result["reason"] = stderr.strip() or f"http_{status}"
        manifest["failures"].append({"wd": f"{wd}/{revision}", "reason": result["reason"]})
    write_json_atomic(manifest_path, manifest)
    return result


def fetch_latest(wd: str) -> dict:
    """Resolve and cache the newest revision of a known WD number."""
    try:
        manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8")) if VALIDATION_MANIFEST.exists() else {}
    except json.JSONDecodeError:
        manifest = {}
    manifest.setdefault("method", "known_url_direct_fetch")
    manifest.setdefault("requests", 0)
    manifest.setdefault("pages_cached", 0)
    manifest.setdefault("failures", [])
    manifest.setdefault("documents", [])
    if manifest["requests"] >= 60:
        return {"wd": wd, "status": 0, "reason": "validation_request_cap"}
    if manifest["requests"]:
        time.sleep(1)
    manifest["requests"] += 1
    status, history, stderr = run_curl(f"{BASE}/{wd}/history")
    if status != 200:
        reason = stderr.strip() or f"http_{status}"
        manifest["failures"].append({"wd": wd, "reason": reason})
        write_json_atomic(VALIDATION_MANIFEST, manifest)
        return {"wd": wd, "status": status, "reason": reason}
    try:
        history_data = json.loads(history.decode("utf-8"))
        (CACHE / f"{wd}.history.json").write_text(json.dumps(history_data), encoding="utf-8")
        revision = latest_revision(history_data)
    except json.JSONDecodeError:
        revision = None
    write_json_atomic(VALIDATION_MANIFEST, manifest)
    if revision is None:
        return {"wd": wd, "status": 200, "reason": "history_without_revision"}
    return fetch_direct(wd, revision)


def rollover_ids_by_state() -> dict[str, list[str]]:
    """Read SAM's official crosswalk to avoid speculative ID probes."""
    if not ROLLOVER_CROSSWALK.exists():
        raise FileNotFoundError(f"Missing {ROLLOVER_CROSSWALK}")
    import re
    ids: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for wd in re.findall(r"\b([A-Z]{2}2026\d{4})\b", ROLLOVER_CROSSWALK.read_bytes().decode("latin1")):
        if wd not in seen:
            ids[wd[:2]].append(wd)
            seen.add(wd)
    return ids


def coverage_priority_states() -> list[str]:
    wages = {r["lu_number"]: r for r in load_csv("out/local_wage_davisbacon.csv")}
    population: dict[str, float] = defaultdict(float)
    for target in load_csv("out/targets_with_population.csv"):
        wage = wages.get(target["lu_number"], {})
        if wage.get("is_union_rate") != "true":
            population[target.get("charter_state", "")] += float(target.get("population_current_served_inside") or 0)
    return [state for state, _ in sorted(population.items(), key=lambda item: (-item[1], item[0])) if state]


def gap_coverage_priority_states() -> list[str]:
    """Prioritize only the coverage-analysis rows where more pulls can help."""
    population: dict[str, float] = defaultdict(float)
    for row in load_csv("out/davisbacon_coverage_analysis.csv"):
        if row.get("verdict") == "not_pulled":
            population[row.get("state", "")] += float(row.get("population") or 0)
    return [state for state, _ in sorted(population.items(), key=lambda item: (-item[1], item[0])) if state]


def gap_coverage_pull(cap: int, batch: int | None = None) -> dict:
    """Use the extra budget only for states marked not_pulled by analysis."""
    ids_by_state = rollover_ids_by_state()
    manifest = {"method": "coverage_analysis_not_pulled_crosswalk_direct_revision_zero", "requests": 0,
                "pages_cached": 0, "failures": [], "documents": [], "state_curve": []}
    if GAP_COVERAGE_MANIFEST.exists():
        try:
            manifest.update(json.loads(GAP_COVERAGE_MANIFEST.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    manifest["request_cap"] = cap
    manifest["method"] = "coverage_analysis_not_pulled_crosswalk_direct_revision_zero"
    manifest.setdefault("state_curve", [])
    write_json_atomic(GAP_COVERAGE_MANIFEST, manifest)
    run_cap = min(cap, manifest["requests"] + batch) if batch else cap
    finished = {row["state"] for row in manifest["state_curve"]}
    for state in gap_coverage_priority_states():
        if state in finished or manifest["requests"] >= run_cap:
            continue
        if manifest.get("active_state") != state:
            manifest["active_state"] = state
            manifest["active_start_requests"] = manifest["requests"]
            manifest["active_before_codes"] = len({r.get("local_number_from_code") for r in parse_cache()
                                                     if r.get("is_union_rate") == "true" and r.get("work_classification") == "inside_wireman"})
            manifest["active_documents"] = 0
            write_json_atomic(GAP_COVERAGE_MANIFEST, manifest)
        for wd in ids_by_state.get(state, []):
            if manifest["requests"] >= run_cap:
                break
            result = fetch_direct(wd, 0, GAP_COVERAGE_MANIFEST, run_cap)
            manifest = json.loads(GAP_COVERAGE_MANIFEST.read_text(encoding="utf-8"))
            manifest["active_documents"] = int(manifest.get("active_documents", 0)) + int(result.get("status") == 200 and not result.get("reason"))
            write_json_atomic(GAP_COVERAGE_MANIFEST, manifest)
        if manifest["requests"] >= run_cap and run_cap < cap:
            manifest["stop_reason"] = "batch_checkpoint"
            write_json_atomic(GAP_COVERAGE_MANIFEST, manifest)
            return manifest
        after = len({r.get("local_number_from_code") for r in parse_cache()
                     if r.get("is_union_rate") == "true" and r.get("work_classification") == "inside_wireman"})
        record = {"state": state, "requests": manifest["requests"] - int(manifest.get("active_start_requests", manifest["requests"])),
                  "documents": int(manifest.get("active_documents", 0)),
                  "new_locals": max(0, after - int(manifest.get("active_before_codes", after))), "cumulative_locals": after}
        manifest["state_curve"].append(record)
        for key in ("active_state", "active_start_requests", "active_before_codes", "active_documents"):
            manifest.pop(key, None)
        write_json_atomic(GAP_COVERAGE_MANIFEST, manifest)
        if manifest["requests"] >= cap:
            manifest["stop_reason"] = "request_cap"
            break
        if len(manifest["state_curve"]) >= 2 and all(r["new_locals"] == 0 for r in manifest["state_curve"][-2:]):
            manifest["stop_reason"] = "early_stop_two_states_zero_new_locals"
            break
    manifest["stop_reason"] = manifest.get("stop_reason", "request_cap" if manifest["requests"] >= cap else "state_list_exhausted")
    write_json_atomic(GAP_COVERAGE_MANIFEST, manifest)
    return manifest


def coverage_pull(cap: int, batch: int | None = None) -> dict:
    """Fetch known revision-zero documents, prioritized by uncovered population."""
    ids_by_state = rollover_ids_by_state()
    manifest = {"method": "sam_rollover_crosswalk_direct_revision_zero", "requests": 0, "pages_cached": 0,
                "failures": [], "documents": [], "state_curve": []}
    if COVERAGE_MANIFEST.exists():
        try:
            manifest.update(json.loads(COVERAGE_MANIFEST.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            recovered = sorted(CACHE.glob("*2026*_0.json"))
            manifest.update({"requests": len(recovered), "pages_cached": len(recovered),
                             "documents": [path.stem.replace("_", "/") for path in recovered],
                             "recovered_after_interrupted_manifest_write": True})
    manifest["request_cap"] = cap
    manifest["method"] = "sam_rollover_crosswalk_direct_revision_zero"
    manifest.setdefault("state_curve", [])
    write_json_atomic(COVERAGE_MANIFEST, manifest)
    run_cap = min(cap, manifest["requests"] + batch) if batch else cap
    for state in coverage_priority_states():
        if manifest["requests"] >= run_cap:
            break
        before = len({r.get("local_number_from_code") for r in parse_cache() if r.get("is_union_rate") == "true" and r.get("work_classification") == "inside_wireman"})
        started = manifest["requests"]
        cached = 0
        for wd in ids_by_state.get(state, []):
            if manifest["requests"] >= run_cap:
                break
            result = fetch_direct(wd, 0, COVERAGE_MANIFEST, run_cap)
            cached += int(result.get("status") == 200 and not result.get("reason"))
            # fetch_direct owns durable request accounting; reload it so this
            # loop observes the cap instead of a stale in-memory manifest.
            manifest = json.loads(COVERAGE_MANIFEST.read_text(encoding="utf-8"))
        if manifest["requests"] >= run_cap and run_cap < cap:
            # A partial state is deliberately checkpointed without a full
            # cache reparse.  The next batch resumes the same known IDs, and
            # the completed-state curve remains meaningful.
            manifest["stop_reason"] = "batch_checkpoint"
            write_json_atomic(COVERAGE_MANIFEST, manifest)
            return manifest
        after = len({r.get("local_number_from_code") for r in parse_cache() if r.get("is_union_rate") == "true" and r.get("work_classification") == "inside_wireman"})
        record = {"state": state, "requests": manifest["requests"] - started, "documents": cached,
                  "new_locals": max(0, after - before), "cumulative_locals": after}
        manifest.setdefault("state_curve", []).append(record)
        write_json_atomic(COVERAGE_MANIFEST, manifest)
        tail = manifest["state_curve"][-3:]
        if len(tail) == 3 and all(r["new_locals"] < 2 for r in tail):
            manifest["stop_reason"] = "early_stop_three_states_under_two_locals"
            break
    manifest["stop_reason"] = (
        "request_cap" if manifest["requests"] >= cap else
        "batch_checkpoint" if manifest["requests"] >= run_cap else
        manifest.get("stop_reason", "state_list_exhausted")
    )
    write_json_atomic(COVERAGE_MANIFEST, manifest)
    return manifest


def request_json(url: str, manifest: dict, key: str) -> tuple[int, dict | None, str]:
    """Cache only successful JSON. Retries are individually counted."""
    for attempt in range(3):
        if manifest["requests"] >= manifest["request_cap"]:
            return 0, None, "request_cap"
        if manifest["requests"]:
            time.sleep(1)
        manifest["requests"] += 1
        status, body, stderr = run_curl(url)
        if status == 200:
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return status, None, "invalid_json"
            return status, data, ""
        if status in (403, 429):
            return status, None, f"rate_or_access_{status}"
        if status == 404:
            return status, None, "not_found"
        if attempt < 2:
            time.sleep(2 ** attempt)
            continue
        return status, None, stderr.strip() or f"http_{status}"
    return 0, None, "unreachable"


def latest_revision(history: dict) -> int | None:
    rows = (history.get("_embedded") or {}).get("wageDetermination") or []
    active = [r for r in rows if r.get("active")]
    candidate = max(active or rows, key=lambda r: int(r.get("revisionNumber", -1)), default=None)
    return int(candidate["revisionNumber"]) if candidate and candidate.get("revisionNumber") is not None else None


def pull(cap: int, sequence_limit: int) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    manifest["request_cap"] = cap
    manifest.setdefault("state_curve", [])
    known_states = {r.get("state") for r in manifest.get("states", [])}
    for state in target_states():
        if state in known_states or manifest["requests"] >= cap:
            continue
        before = len({r.get("local_number_from_code") for r in parse_cache() if r.get("is_union_rate") == "true"})
        state_record = {"state": state, "probes": 0, "documents": 0, "new_locals": 0, "cumulative_locals": before}
        for sequence in range(1, sequence_limit + 1):
            if manifest["requests"] >= cap:
                break
            wd = f"{state}2026{sequence:04d}"
            history_path = CACHE / f"{wd}.history.json"
            if history_path.exists():
                try:
                    history = json.loads(history_path.read_text(encoding="utf-8"))
                    status, reason = 200, ""
                except json.JSONDecodeError:
                    status, history, reason = 0, None, "bad_cached_history"
            else:
                status, history, reason = request_json(f"{BASE}/{wd}/history", manifest, wd)
                state_record["probes"] += 1
                if status == 200 and history is not None:
                    history_path.write_text(json.dumps(history), encoding="utf-8")
            if status == 404:
                continue
            if status in (403, 429):
                manifest["failures"].append({"wd": wd, "reason": reason})
                save_manifest(manifest)
                break
            if not history:
                if reason not in ("not_found", "request_cap"):
                    manifest["failures"].append({"wd": wd, "reason": reason})
                continue
            revision = latest_revision(history)
            if revision is None:
                manifest["failures"].append({"wd": wd, "reason": "history_without_revision"})
                continue
            document_path = CACHE / f"{wd}_{revision}.json"
            if not document_path.exists():
                status, document, reason = request_json(f"{BASE}/{wd}/{revision}", manifest, wd)
                if status == 200 and document is not None:
                    document_path.write_text(json.dumps(document), encoding="utf-8")
                    manifest["pages_cached"] += 1
                elif reason:
                    manifest["failures"].append({"wd": wd, "reason": reason})
                    if status in (403, 429):
                        save_manifest(manifest)
                        break
            state_record["documents"] += int(document_path.exists())
        parsed = parse_cache()
        after = len({r.get("local_number_from_code") for r in parsed if r.get("is_union_rate") == "true"})
        state_record["new_locals"] = max(0, after - before)
        state_record["cumulative_locals"] = after
        manifest["states"].append(state_record)
        manifest["state_curve"].append(state_record)
        save_manifest(manifest)
        tail = manifest["state_curve"][-3:]
        if len(tail) == 3 and all(r["new_locals"] < 2 for r in tail):
            manifest["stop_reason"] = "early_stop_three_states_under_two_locals"
            break
    manifest.setdefault("stop_reason", "request_cap" if manifest["requests"] >= cap else "state_list_exhausted")
    save_manifest(manifest)
    with BLOCKERS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["wd_number", "blocker", "details"])
        w.writeheader()
        for item in manifest.get("failures", []):
            w.writerow({"wd_number": item.get("wd", ""), "blocker": "fetch_failure", "details": item.get("reason", "")})
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--cap", type=int, default=400)
    parser.add_argument("--sequence-limit", type=int, default=12)
    parser.add_argument("--direct", action="append", default=[], metavar="WD/REV")
    parser.add_argument("--latest", action="append", default=[], metavar="WD")
    parser.add_argument("--coverage", action="store_true", help="use cached SAM rollover crosswalk; default cap 300")
    parser.add_argument("--coverage-batch", type=int, help="checkpoint a coverage pull after this many new requests")
    parser.add_argument("--gap-coverage", action="store_true", help="pull only states marked not_pulled by coverage analysis")
    args = parser.parse_args()
    if args.direct or args.latest:
        results = []
        for token in args.direct:
            wd, sep, revision = token.strip().upper().partition("/")
            if not sep or not wd or not revision.isdigit():
                raise SystemExit(f"--direct requires WD/REV, got {token!r}")
            results.append(fetch_direct(wd, int(revision)))
        for wd in args.latest:
            results.append(fetch_latest(wd.strip().upper()))
        print(json.dumps(results, indent=2))
        return
    if args.gap_coverage:
        manifest = gap_coverage_pull(args.cap, args.coverage_batch)
        print(json.dumps({k: manifest.get(k) for k in ("method", "requests", "pages_cached", "stop_reason", "state_curve")}, indent=2))
        return
    if args.coverage:
        manifest = coverage_pull(args.cap, args.coverage_batch)
        print(json.dumps({k: manifest.get(k) for k in ("method", "requests", "pages_cached", "stop_reason", "state_curve")}, indent=2))
        return
    if not args.pull:
        raise SystemExit("Refusing network access without --pull. Use parse_davisbacon.py for cache-only parsing.")
    manifest = pull(args.cap, args.sequence_limit)
    print(json.dumps({k: manifest.get(k) for k in ("method", "requests", "pages_cached", "stop_reason", "state_curve")}, indent=2))


if __name__ == "__main__":
    main()
