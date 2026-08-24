# Claude Code task: IBEW status pipeline, fix round 2

Working dir is this repo (`~/ibew`). Round 1 is committed and verified
(`8565d44`, `c0a166a`, `76a9a1d`, `52afaa7`). This round is still zero paid API
cost, but it is longer running and I will be away. Work through all seven tasks
without stopping.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl calls. No re-extraction.** Nothing here
  needs an LLM or a paid crawl. If you conclude a task does, skip that task, log it
  in `out/round2_blockers.csv`, and move on. Do not spend credits.
- **Do not run any `pass*.py` script.**
- **Do not read anything under `raw/`** except `raw/scrape/complete_lus.json`. There
  are 3,453 HTML pages and 1,528 JSON files down there. Everything you need is in
  `out/*.csv`.
- **Never write `out/extraction_v2.csv`.** Read-only, it is the extraction record of
  truth.
- **I am not available.** Do not stop to ask questions. If you hit a real blocker,
  append a row to `out/round2_blockers.csv` (`task`, `blocker`, `what_i_did_instead`)
  and continue to the next task.
- One commit per numbered task. Run the full test suite before each commit.
- Task 5 makes 215 plain HTTP GETs. That is free and intended. No other network.

## State you do not need to rediscover

Verified as of round 1, take as given:

- `extraction_v2.csv`: 242 rows, `lu_number` unique within it.
- Full 242 recompute: unknown 116, rolling 79, closed_pending 14, closed 13,
  conflicting 10, open 5, expired_data 5.
- `out/verify_worklist.csv`: 120 rows. rolling 73, closed_pending 14, closed 13,
  conflicting 10, expired_data 5, open 5. Confidence: medium 73, high 31, low 16.
- `out/shippable.csv`: 26,459 ZIP rows, 120 locals, `is_stale` empty everywhere.
- `compute_status.py`: 13 tests, all passing, `TODAY = 2026-08-10` in the test class.
- Window `precision` values: absolute 89, recurring 74, none 22, relative 12.
- `content_year` is the highest year mentioned on the page, not a freshness signal.
  It is exposed as `max_year_mentioned`.

## Task 1: timing gate on rolling statements

**Bug.** `compute_status` trusts `statement_type == 'rolling'`. The extractor is
putting `application_method` content into `status_statements` labelled `rolling`.
18 of the 79 rolling locals have rolling statements with no temporal information at
all, only method. Examples, verbatim:

- LU 340 Sacramento (3.2M): "Applicants Apply Online"
- LU 683 Columbus (2.1M): "create an online account through our website"
- LU 136 Birmingham (2.0M): "You will need to create an account on our online application portal"
- LU 584 Tulsa (1.6M): "Apply through our portal."
- LU 666 Richmond (1.5M): "All applicants must apply through the online process."
- LU 13 Burlington: "All applications are submitted online only."

Four of the eight locals that survive as `rolling`/`high` are in this set:
233, 666, 873, 415.

**Fix.** A `rolling` statement only counts as rolling evidence if its
`verbatim_text` carries temporal language. Implement as a module-level function
`classify_intake(text)` returning one of:

- `continuous` — year round, year-long, all year, continuously, ongoing,
  at any time, anytime, at all times, always, no deadline, open enrollment,
  throughout the year, accepted at all times
- `periodic` — daily, weekly, monthly, quarterly, every/each + weekday,
  bare plural weekday ("Tuesdays", "on Wednesdays"), weekday ranges
  ("Monday through Friday", "Mon-Fri"), nth weekday of the month
  ("third Monday of the month", "first three days of the month")
- `none` — everything else, including anything that only describes method
  (online, portal, website, in person at an address, call the office,
  create an account, click the link)

Then in `compute_status`:

- Rolling statements classifying as `none` are **ignored as status evidence.** They
  do not trigger the rolling branch and they do not trigger the `conflicting`
  branch from round 1. If nothing else resolves the local it falls through to
  `unknown` / `low`, which is the correct and safe answer.
- Add `intake_pattern` to the returned dict: `continuous`, `periodic`, or empty.
  Only populated when `computed_status` is `rolling`. This is a real product
  distinction. "Accepting year round" and "accepting Tuesdays 9-11:30 in person"
  need different copy, and right now they are indistinguishable downstream.
- A local whose rolling evidence is `periodic` only is capped at `medium`
  confidence.

**This gate is a heuristic and I know it.** Two requirements because of that:

1. Define the keyword sets as named module-level constants with a comment saying
   they are heuristic and reviewable. Do not bury regexes inside the function body.
2. It may only ever **demote**. It must never turn `unknown` into `rolling` or raise
   a confidence level. Demoting a genuinely-open local costs me one lead and shows
   the official application link. Promoting a closed local to "apply now" costs the
   only asset I have.

Three known regex traps that must classify as `periodic`, not `none`: LU 375
("submitted in person at the main union hall ... on Tuesdays"), LU 681
("taken each Wednesday of the month from 1—5 PM"), LU 873 ("In person on Tuesdays
from 9am - 11:30am"). Those are real intake schedules and demoting them would be a
false negative.

## Task 2: tests for the gate

Extend the existing test class, keep `TODAY = 2026-08-10`, all 13 existing tests must
still pass. Add:

- `classify_intake` unit tests: at least 6 `continuous` phrasings, 8 `periodic`
  phrasings including the three traps above, and 8 `none` phrasings drawn from the
  method-only quotes in task 1.
- method-only rolling statement alone → `unknown` / `low`, `intake_pattern` empty
- method-only rolling + a closed statement → `closed`, NOT `conflicting`
  (the rolling statement was never real evidence, so there is no conflict)
- `continuous` rolling, fresh → `rolling` / `high`, `intake_pattern='continuous'`
- `periodic` rolling, fresh → `rolling` / `medium`, `intake_pattern='periodic'`
- `continuous` rolling with evidence 400 days old → `rolling` / `low`
  (round 2 gate must not undo the round 1 age cap)

Paste full test output. If an existing test fails, do not edit it. Log it in
`out/round2_blockers.csv` and tell me.

## Task 3: `out/statement_label_audit.csv`

The rolling mislabel is one instance of a general problem, and I want to see the
whole surface, not just the part that bit me. Audit **every** statement across all
242 locals and all `statement_type` values, not just rolling.

One row per statement: `local_union_id`, `lu_number`, `statement_type`,
`verbatim_text` (truncate 300), `stated_effective_date`, `source_url`,
`classify_intake_result`, `disagreement_flag`, `disagreement_reason`.

Flag a disagreement where the text does not support the label. At minimum detect:

- `rolling` with `classify_intake == 'none'` (the task 1 defect)
- `closed` whose text contains no closure language (closed, not accepting, not
  currently, suspended, list is full, no longer accepting)
- `reopening` with no `stated_effective_date` and no future date in the text
- `open` whose text describes method or eligibility rather than status
- any statement whose text is pure eligibility or requirements content (must be 18,
  high school diploma, valid driver's license, transcript, DD-214) and is therefore
  not a status statement at all

Sort disagreements first, then by population descending. Print a count by
`statement_type` and by `disagreement_reason`.

## Task 4: `out/window_label_audit.csv`

Same exercise for the windows array, where I already know office hours are being
stored as application windows (LU 531 "Mon-Fri 8:00 a.m. - 4:00 p.m. excludes lunch
hour", LU 159 "closed on the 4th Friday of each month", LU 601 "Summer Hours for
applications: Wednesdays 12:30-3").

One row per window: `local_union_id`, `lu_number`, `precision`, `open_date`,
`close_date`, `open_month`, `open_day`, `close_month`, `close_day`,
`is_recurring_annual`, `relative_description` (300), `evidence_quote` (300),
`source_url`, `suspect_flag`, `suspect_reason`.

Suspect reasons to detect at minimum:

- clock times present but no calendar dates or months anywhere → office hours, not a
  window
- `relative_description` describes a closure rather than an opening
- `precision == 'absolute'` but `open_date` and `close_date` are both empty
- `precision == 'recurring'` with `is_recurring_annual` false and no month fields,
  which is not a resolvable window
- `close_date` earlier than `open_date`
- any date more than 2 years in the future

Also report: of the 30 `unknown` locals with non-absolute windows, how many have at
least one window that survives this audit as genuine. I believe it is around 7
(490, 231, 82, 305, 7, 73, 449). Confirm or correct.

## Task 5: monitor.py baseline sweep

Run the full sweep, all 215 URLs, sequential with the 1s sleep. Roughly 5 minutes.
This establishes the hash baseline, which is the only trustworthy freshness signal
in the system, so everything downstream depends on it existing.

- **Do not call Firecrawl on any change.** First run, everything is new, there is
  nothing to diff against. Just write state.
- Report: URLs attempted, 200s, non-200s by status code, timeouts, total failures,
  and the failure list with `lu_number` and reason.
- Confirm `out/monitor_state.json` is keyed by `local_union_id` and has one record
  per distinct URL.
- If a domain fails all retries, that is data, not an error. Log and continue.
- If more than 25% of URLs fail, stop the sweep, log it as a blocker, and tell me.
  That would mean something is wrong with the runner, not with 54 union websites.

## Task 6: cross-validate against the competitor

`out/sparky_coverage_117.csv` is competitor coverage for the 117 locals they cover.
Inspect its header first and adapt, I do not remember the exact columns.
`validate_against_sparky.py` and `coverage_diff.py` already exist, read them before
writing anything new.

Produce `out/status_disagreement.csv`: locals where I have a computed status and they
publish a status, and the two disagree. Columns: `local_union_id`, `lu_number`,
`charter_city`, `population_current_served_inside`, `my_computed_status`,
`my_status_confidence`, `my_intake_pattern`, `their_status`, `agreement`
(`agree` / `disagree` / `not_comparable`), `my_evidence_quote` (300), `my_source_url`.

Normalize both sides to a comparable vocabulary before comparing, and put the mapping
you used in a comment. Do not silently coerce. Where their vocabulary has no
equivalent of mine (`conflicting`, `expired_data`, `unknown`), mark
`not_comparable` rather than forcing a call.

Print the agreement rate and the disagreement count. **Their status is not ground
truth**, they are a second opinion from someone with better trade access than me.
Disagreements are a prioritized review queue, not a list of my errors.

## Task 7: rebuild the worklist, sorted by risk

Rewrite `build_verify_worklist.py` output. Still 120 rows, same columns as before,
plus `intake_pattern`, `risk_score`, `risk_flags`.

`risk_flags` is a pipe-delimited list of anything true for that local:

- `method_only_rolling` (task 1 gate demoted it)
- `conflicting`
- `statement_label_disagreement` (task 3)
- `suspect_window` (task 4)
- `competitor_disagreement` (task 6)
- `stale_evidence` (`days_since_evidence` > 365)
- `no_dated_evidence` (`days_since_evidence` is null)
- `max_year_mentioned` < 2026
- `periodic_intake_only`

`risk_score` = count of flags, weighted by `population_current_served_inside`. Define
the weighting in a comment, keep it simple, and make it monotonic: more flags and more
population both push the score up.

Sort descending by `risk_score`. This is my manual verification queue. I want to work
the top 50 by consequence of being wrong, not by raw population, because a
high-population local with clean high-confidence continuous evidence needs less of my
attention than a 300k local whose status rests on "Apply through our portal."

Also re-run `build_shippable.py` so it picks up the new statuses, and confirm the row
and local counts. If they moved off 26,459 / 120, tell me why.

## Out of scope

- Re-extraction of anything. The label defects in tasks 3 and 4 get **audited** this
  round, not fixed. Fixing them means re-running extraction and that costs money, so
  it is my decision after I read the audits.
- LU 43, 106, 306, 257, 349 (no extraction, needs crawling).
- The 26 locals with no `application_url`.
- Trademark, domains, website, app, content.

## Report back

Short and factual. Per task: what changed, the count or test output that proves it,
the commit. Then:

1. Final status distribution across all 242 and across the 120.
2. How many of the 120 survive as displayable, meaning a real status, confidence not
   `low`, and zero risk flags. This is the number I actually care about.
3. The top 15 rows of the risk-sorted worklist, as a table.
4. Anything you found that I have not accounted for.

No summary document. The CSVs and this report are the deliverable.
