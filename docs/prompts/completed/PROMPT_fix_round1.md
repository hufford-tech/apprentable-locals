# Claude Code task: IBEW status pipeline, fix round 1

Working dir is this repo (`~/ibew`). Everything below is zero-paid-API-cost work.

## HARD CONSTRAINTS, read before doing anything

- **No Anthropic API calls. No Firecrawl calls. No re-extraction.** Nothing in this
  task requires an LLM or a paid crawl. If you think it does, stop and tell me why
  instead of spending credits.
- **Do not run any `pass*.py` script.** They crawl and extract. They are done.
- **Do not read anything under `raw/`.** It is 3,453 HTML pages plus 1,528 JSON
  files. You will burn context for no reason. Everything you need is in `out/*.csv`.
- **Do not rewrite `out/extraction_v2.csv`.** It is the extraction record of truth.
  Read it, never write it.
- Only network activity permitted: plain `requests` GETs in task 4, and only when I
  explicitly run it. Do not fire it as part of building it.
- Read only these files: `compute_status.py`, `build_shippable.py`,
  `out/extraction_v2.csv` (header + via csv module, do not cat it),
  `out/targets_with_population.csv`, `out/computed_status.csv`,
  `raw/scrape/complete_lus.json`.
- Work in small commits. One commit per numbered task.

## Context you do not need to rediscover

Already verified, take these as given:

- `extraction_v2.csv` has 242 rows, `lu_number` is unique within it.
- Window `precision` values present: absolute 89, recurring 74, none 22, relative 12.
  There is no longer any `precision='rolling'`. That defect is already fixed.
- `computed_status.csv`: unknown 116, rolling 89, closed_pending 14, closed 13,
  open 5, expired_data 5.
- `complete_lus.json` yields 120 locals. `out/shippable.csv` currently has 26,459
  ZIP rows across those 120.
- `content_year` is NOT a freshness field. It is the highest year mentioned anywhere
  on the page. 24 locals read 2027, LU 343 reads 2031, LU 934 reads 2029, LU 292
  reads 2028. `page_last_updated` is empty for nearly every row.

## Task 1: fix rule precedence in `compute_status.py`

**Bug:** rule 1 returns `rolling` whenever any statement has
`statement_type == 'rolling'`, before it ever inspects `closed_statements` or
`reopening_statements`. Ten locals carry a rolling statement AND a closed statement
and all ten compute to `rolling`. LU 292 has 3 closed and 2 rolling. LU 80 has 2
closed and 1 rolling. This is the LU 164 failure mode moved from windows to
statements: it renders "apply now" for a local that is not accepting.

**Fix:** add a new `computed_status` value `conflicting`. Do not try to guess which
statement is current from text. Rule order becomes:

1. If rolling statements exist AND (closed statements OR reopening statements exist)
   → `conflicting`, confidence `low`.
2. If rolling statements exist and nothing contradicts → `rolling`.
3. Everything after that is unchanged.

`conflicting` means "human must read the page." It is never displayed as a status.

Affected locals, all ten must come out `conflicting` after the fix:
557, 948, 80, 968, 347, 175, 995, 292, 426, 540.

## Task 2: cap confidence by evidence age, same file

**Bug:** the rolling branch never looks at `days_since_evidence`. LU 194 returns
`rolling` / `high` on a page whose only date is 2006-10-31, which is 7,224 days ago.
LU 661 is 2,974 days. Six rolling locals have evidence older than a year.

**Fix:** apply a cap to the returned `status_confidence` in one place, after the
branch has been chosen, so it cannot be forgotten in a future branch. Rules:

- `days_since_evidence` is None (no dated evidence of any kind) → cap at `medium`
- `days_since_evidence` > 180 → cap at `medium`
- `days_since_evidence` > 365 → cap at `low`

Cap means downgrade only, never upgrade. Implement as a small helper, not inline in
each return.

Note in a docstring comment: once `monitor.py` has hash history, `last_changed`
becomes a real floor for `days_since_evidence`. It is the only trustworthy freshness
signal in this system. Leave a TODO where that plugs in.

## Task 3: unit tests for both, in the existing test class

Add tests, keep `TODAY = 2026-08-10` so the existing four LU regression tests still
pass. New cases:

- rolling + closed → `conflicting` / `low` (model on LU 292)
- rolling + reopening → `conflicting` (model on LU 557)
- rolling only, `page_last_updated` 2006-10-31 → `rolling` but confidence `low`
  (model on LU 194)
- rolling only, no dates at all → `rolling`, confidence `medium` not `high`
- confirm `open` inside a current window still returns `high`

Run `python compute_status.py` and paste the full test output. All existing tests
must still pass. If any existing test now fails, stop and show me before changing it.

## Task 4: `monitor.py`, plain requests, no Firecrawl

Build it, do not run the full sweep.

- Input: the distinct `application_url` values from `extraction_v2.csv`. Skip empty.
  Report how many URLs that is.
- For each: `requests.get` with a real User-Agent, 15s timeout, 2 retries with
  backoff. Strip `<script>` and `<style>`, collapse all whitespace to single spaces,
  lowercase, then sha256.
- State file `out/monitor_state.json`, keyed by `local_union_id` not `lu_number`
  (see task 6). Per record: `url`, `last_hash`, `last_checked`, `last_changed`,
  `consecutive_failures`, `last_http_status`.
- On hash change: update `last_changed` and append a row to
  `out/monitor_changes.csv`. **Do not call Firecrawl.** Firecrawl is a separate
  manual step I trigger after reviewing the change log.
- `consecutive_failures >= 3` → log to `out/monitor_failures.csv` and keep going.
- Sequential, 1s sleep between requests. No threads. I want this polite, not fast.
- Add `--limit N` and `--dry-run` flags. Verify it works with `--limit 3` only.
  That is 3 HTTP requests, nothing more.

## Task 5: `out/verify_worklist.csv`, the actual gate artifact

`shippable.csv` is the wrong shape for verification. It is 26,459 ZIP rows and
verification happens per local. Write a new script `build_verify_worklist.py` that
emits **one row per local, 120 rows**, sorted descending by
`population_current_served_inside`:

```
local_union_id, lu_number, charter_city, charter_state,
population_current_served_inside, application_url, computed_status,
status_confidence, days_since_evidence, max_year_mentioned,
window_count, status_statement_count, evidence_quote, source_url,
verified_by, verified_date, verified_status, notes
```

- `evidence_quote`: the single most decisive verbatim string. Prefer the
  `verbatim_text` of the statement that drove the computed status; if the status came
  from a window, use that window's `evidence_quote`. Truncate to 300 chars. This is
  the whole point of the file, so a human can check the call without opening the page.
- `source_url`: the `source_url` on that same statement or window.
- `max_year_mentioned`: pass `content_year` through under the honest name.
- Last four columns ship empty. They are for me to fill by hand.

## Task 6: stop lying about staleness, and fix the primary key

In `build_shippable.py`:

- Delete the `is_stale` derivation. `int(content_year) < 2026` is not a staleness
  test, for the reasons in the context section. Emit `is_stale` as empty string for
  every row until `monitor.py` has history, and add `max_year_mentioned` as a
  passthrough column so the signal is not lost.
- Every join currently keys on `lu_number`. My primary key is `local_union_id`.
  It is harmless today because `lu_number` is unique across these 242 rows, but it
  breaks the moment I go past class-i. Re-key the joins on `local_union_id`, using
  `targets_with_population.csv` as the crosswalk. Add an assertion that every
  `lu_number` in `extraction_v2.csv` resolves to exactly one `local_union_id`, and
  fail loudly if not.
- Re-run it and confirm the row count and distinct-local count are unchanged at
  26,459 and 120.

## Out of scope, do not touch

- The 30 `unknown` locals with non-absolute windows. Only 7 are cleanly resolvable
  and the other 26 are contaminated with office hours (LU 531 "Mon-Fri 8-4",
  LU 159 "closed the 4th Friday", LU 601 "summer hours"). That is an extraction
  schema problem, not a `compute_status` problem. Separate task, later.
- LU 43, 106, 306, 257, 349 (no extraction). Needs crawling. Costs money. Not now.
- The 26 locals with no `application_url`.
- Anything to do with the website, app, or content.

## Report back

Short. For each task: what changed, the test or count that proves it, and the commit.
Then flag anything you found that I have not accounted for. Do not write a summary
document.
