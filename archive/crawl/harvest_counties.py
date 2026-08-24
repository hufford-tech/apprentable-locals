import json
import os
import random
import time

import requests

BASE = "https://ibewapp.org/ludSearch/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

RAW_DIR = "raw"
COUNTIES_DIR = os.path.join(RAW_DIR, "counties")
os.makedirs(COUNTIES_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE + "lusStart.htm",
})
session.get(BASE + "lusStart.htm", timeout=30)


def is_error_response(resp):
    ctype = resp.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        return True
    stripped = resp.text.lstrip()
    if stripped[:1] == "<":
        return True
    return False


def fetch(action, params=None):
    p = {"action": action}
    if params:
        p.update(params)
    return session.get(BASE + "DataIO.ashx", params=p, timeout=30)


def save_raw(path, resp):
    with open(path, "wb") as f:
        f.write(resp.content)


def main():
    with open(os.path.join(RAW_DIR, "list_locals.json"), encoding="utf-8") as f:
        locals_list = json.load(f)

    print(f"Total locals to process: {len(locals_list)}")

    failures = []
    consecutive_failures = 0
    processed = 0
    succeeded = 0

    for rec in locals_list:
        local_id = rec["ID"]
        lu = rec["LU"]
        out_path = os.path.join(COUNTIES_DIR, f"{lu}.json")

        if os.path.exists(out_path):
            continue

        processed += 1
        attempt_info = None
        ok = False

        for attempt in (1, 2):
            try:
                resp = fetch("list-local-counties", {"lu": lu})
            except requests.RequestException as e:
                attempt_info = {
                    "ID": local_id, "LU": lu, "status": None, "content_type": None,
                    "body_snippet": f"RequestException: {e}",
                }
                if attempt == 1:
                    time.sleep(5)
                    continue
                else:
                    break

            if not is_error_response(resp):
                save_raw(out_path, resp)
                ok = True
                break
            else:
                attempt_info = {
                    "ID": local_id, "LU": lu, "status": resp.status_code,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "body_snippet": resp.text[:200],
                }
                if attempt == 1:
                    time.sleep(5)
                    continue

        if ok:
            succeeded += 1
            consecutive_failures = 0
        else:
            failures.append(attempt_info)
            consecutive_failures += 1
            print(f"FAIL LU={lu} ID={local_id}: {attempt_info}")

            if consecutive_failures >= 10:
                print(f"CIRCUIT BREAKER: 10 consecutive failures. Processed {processed}, "
                      f"succeeded {succeeded}, failed {len(failures)}.")
                break
            if processed >= 20 and len(failures) / processed > 0.05:
                print(f"CIRCUIT BREAKER: failure rate {len(failures)}/{processed} exceeds 5%. "
                      f"Succeeded {succeeded}.")
                break

        time.sleep(random.uniform(0.7, 1.4))

    with open(os.path.join(RAW_DIR, "counties_failures.json"), "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2)

    print(f"Done. processed={processed} succeeded={succeeded} failed={len(failures)}")
    print(f"Already-on-disk (skipped) count: {len(locals_list) - processed}")


if __name__ == "__main__":
    main()
