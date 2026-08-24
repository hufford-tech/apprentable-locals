import csv
import datetime
import json
import os

from scrape_lib2 import call_extraction, build_extraction_user_prompt
from pass2_crawl_locals import LOCAL_DIR

CURRENT_YEAR = datetime.date.today().year


def load_local_pages(lu):
    d = os.path.join(LOCAL_DIR, lu)
    pages = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            path = os.path.join(d, fn)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            parts = content.split("\n---\n", 1)
            if len(parts) == 2:
                url, md = parts
                pages.append((url.strip(), md))
    return pages


with open("out/url_validation.csv", encoding="utf-8") as f:
    validation_rows = {r["lu_number"]: r for r in csv.DictReader(f)}
with open("out/locals_joined_olms.csv", encoding="utf-8") as f:
    locals_info = {r["lu_number"]: r for r in csv.DictReader(f)}

lu = "113"
pages = load_local_pages(lu)
v = validation_rows.get(lu, {})
info = locals_info.get(lu, {})

# Print the prompt as constructed, for inspection
prompt = build_extraction_user_prompt(
    lu, info.get("charter_city", ""), pages, CURRENT_YEAR,
    website_corrected=str(v.get("disagreed", "")) == "True",
    original_website=info.get("website", ""),
    state_dol_url="",
)
with open("raw/scrape/lu113_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)
print(f"Prompt written to raw/scrape/lu113_prompt.txt ({len(prompt)} chars)")

extracted, usage = call_extraction(
    lu, info.get("charter_city", ""), pages,
    current_year=CURRENT_YEAR,
    website_corrected=str(v.get("disagreed", "")) == "True",
    original_website=info.get("website", ""),
    state_dol_url="",
)
print(json.dumps(extracted, indent=2))
print(f"\ntokens: input={usage.input_tokens} output={usage.output_tokens} "
      f"cache_read={getattr(usage,'cache_read_input_tokens',0)} cache_write={getattr(usage,'cache_creation_input_tokens',0)}")
