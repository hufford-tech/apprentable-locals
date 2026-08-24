# Claude Code task: IBEW status pipeline, fix round 3

Working dir is this repo (`~/ibew`). Rounds 1 and 2 are committed and verified
(`8565d44`, `c0a166a`, `76a9a1d`, `52afaa7`, `6ff892c`, `c65edea`, `30e7b5d`,
`35cc86d`, `f40049f`). Still zero paid API cost. Nine tasks, work straight through.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl calls. No re-extraction.** If you conclude a
  task needs one, skip it, log it in `out/round3_blockers.csv`, continue.
- **Do not run any `pass*.py` script.**
- **No network at all this round.** Do not re-run the monitor sweep, the baseline from
  round 2 stands.
- **Do not read anything under `raw/`** except `raw/scrape/complete_lus.json`.
- **Never write `out/extraction_v2.csv`.**
- **I am not available.** Do not stop to ask. Log blockers and keep going.
- One commit per numbered task. Full test suite green before every commit.
- Task 8 is the verification gate for this whole round. Do not skip it.

## State you do not need to rediscover

- `compute_status.py`: 21 tests passing, `TODAY = 2026-08-10` in the test class.
  Has `classify_intake()` returning `continuous` / `periodic` / `none`, and returns
  `intake_pattern`.
- Full 242 recompute after round 2: rolling 62, unknown 132, closed_pending 15,
  closed 13, conflicting 10, expired_data 5, open 5.
- `out/verify_worklist.csv`: 120 rows, risk-sorted. rolling 57, unknown 15,
  closed_pending 15, closed 13, conflicting 10, expired_data 5, open 5.
- Displayable (real status, confidence not low, zero risk flags) = 21. Of those, only
  6 are actionable-today: LU 22 Omaha, 72 Waco, 158 Green Bay (rolling), 400 Asbury
  Park, 96 Worcester, 461 Aurora (open). That count of 6 is the number this round
  exists to move.
- `out/shippable.csv`: 26,459 rows / 120 locals.
- Round 2 flag counts on the 120: no_dated_evidence 66, statement_label_disagreement
  37, method_only_rolling 22, suspect_window 18, periodic_intake_only 14,
  conflicting 10, competitor_disagreement 7, stale_evidence 6,
  max_year_mentioned_lt_2026 4.

## Task 1: `classify_intake` requires an application subject, not just a temporal token

**Two bugs, one root cause.** The gate tests for temporal language and nothing else,
so it fires on temporal statements that aren't about applications, and misses
application statements whose temporal phrasing isn't in the keyword list.

False positive, currently surviving as `rolling`/continuous:
LU 349 Miami (4.1M): *"However, new hires could start working anytime during the
year."* That is about when hires begin work, not whether applications are open.

False negative, currently demoted to `unknown`:
LU 606 Orlando (4.3M): *"We accept applications every day through our online
portal."* Unambiguous continuous intake. `every day` is not in the interval list,
only `daily` is.

**Fix.** `classify_intake` must require **both** of:

1. a temporal token (existing `continuous` or `periodic` sets, extended per below), and
2. an **application-subject token**: application, applications, applicant, applicants,
   apply, applying, accept applications, enroll, enrollment, registration, register,
   sign up, intake, take applications, accepting

If a temporal token is present but no application subject, return `none`. Do not
build a blacklist of non-intake subjects. Requiring the positive subject is more
robust than enumerating what to exclude.

Extend the temporal sets:

- `continuous` gains: every day, everyday, all the time, at any point, on a rolling
  basis, rolling basis, continually, perpetually, whenever
- `periodic` gains: bi-weekly, biweekly, semi-monthly, twice a month, every other
  week, first/second/third/fourth + weekday, business days, normal business hours,
  during office hours

Keep both keyword sets as named module-level constants with the heuristic caveat
comment. Still demote-only: this function may never raise a confidence level or turn
`unknown` into a positive status on its own.

**Regression protection.** These six currently pass and must keep passing:
LU 20 Dallas *"Applicants are interviewed and accepted into the program year-round"*,
LU 134 Chicago *"Registration is ongoing for the Electrical (A) and Communications (C)
Programs"*, LU 22 Omaha, LU 72 Waco, LU 158 Green Bay, LU 915 Tampa. Pull their real
`verbatim_text` from `extraction_v2.csv` for the fixtures, do not invent strings.

Report every local whose status or confidence changes as a result, before and after.
I expect LU 606 to gain `rolling` and LU 349 to drop to `unknown`. Anything else that
moves, I want to see.

## Task 2: shared suspect-window predicate

`build_window_label_audit.py` has the suspect-window logic. Task 3 needs the same
logic inside `compute_status`, and I will not have it implemented twice and drift.

Extract it into a new module `window_rules.py` exposing
`is_suspect_window(w) -> (bool, reason)`. Refactor `build_window_label_audit.py` to
import it. Confirm the audit output is byte-identical to the committed version after
the refactor. If it is not, the extraction changed behavior, stop and log it.

## Task 3: teach `compute_status` to read non-absolute windows

**This is the main event.** Rule 2 only accepts `precision == 'absolute'`. Per your
round 2 audit, 26 locals carry genuine window evidence that survives the label audit
and every one of them still computes to `unknown` purely because of this gate.
That is the largest zero-cost recovery left in the repo.

Add a resolution step for recurring windows, running **after** the absolute-window
rule and **before** the existing `expired_data` / `closed` / `unknown` fallbacks.

Eligibility. A window may be resolved only if all hold:

- `is_suspect_window(w)` is False (task 2)
- `precision == 'recurring'`
- `is_recurring_annual` is true, OR both `open_month` and `close_month` are populated
- `open_month` and `close_month` are both populated

Resolution:

- Both months and both days present → build this year's window from month/day.
- Months present, days missing → use day 1 of `open_month` and the last day of
  `close_month`. Cap confidence at `medium` and set a new output field
  `window_precision_note = 'month_boundary_inferred'`.
- **Handle year wrap.** If `close_month` < `open_month`, or the months are equal and
  `close_day` < `open_day`, the window spans a year boundary. Evaluate against both
  the current cycle and the prior cycle.
- Multiple resolvable windows → today inside any of them wins.

Outcomes:

- today inside a resolved window → `open`, confidence `medium` (never `high`, these
  are inferred from a pattern, not a stated date)
- today outside all resolved windows → `closed_pending`, confidence `medium`
- **Add output field `next_open_date`**, the earliest future occurrence across all
  resolved windows, ISO format. Populate it for `closed_pending` from both recurring
  and absolute future windows. This is the most commercially useful field in the
  dataset: it is the email-capture hook ("we will tell you when LU 82 opens on
  September 1"). Empty when not derivable.

Absolute windows keep their existing behavior and can still return `high`. Inferred
windows cap at `medium`, always.

Required test fixtures, all with `TODAY = 2026-08-10`, values pulled from real rows:

| local | window | expected |
|---|---|---|
| LU 490 | Jun 1 → May 20, annual, wraps | `open` / medium |
| LU 82 | Sep 1 → Jun 30, annual, wraps ("No Applications in July or August") | `closed_pending`, `next_open_date` 2026-09-01 |
| LU 305 | Jan 1 → Jan 31, annual, no wrap | `closed_pending`, `next_open_date` 2027-01-01 |
| LU 449 | four quarterly windows incl. Jun 1 → Aug 30 | `open` / medium |
| LU 7 | Sep → Jan, months only, wraps | `closed_pending`, `next_open_date` 2026-09-01, note `month_boundary_inferred` |
| LU 73 | Jan → Mar, months only | `closed_pending`, `next_open_date` 2027-01-01 |
| LU 231 | "one testing date each month (September – May)" | must be rejected by `is_suspect_window`, stays `unknown`. This is a testing schedule, not an application window. |
| LU 531 | "Mon-Fri 8:00 a.m. - 4:00 p.m." | rejected, stays `unknown` |

If LU 231 or LU 531 resolve to a status, the suspect predicate is too permissive.
Fix the predicate, not the test.

## Task 4: fix `method_only_rolling` flag semantics

The flag is specified as "the task 1 gate demoted this local." It is firing on "this
local has at least one method-only statement," which is different. Seven locals carry
it while holding a non-unknown status: 20, 349, 347, 252, 194, 32, 197.

Consequence: LU 20 Dallas-Fort Worth is ranked #1 in my verification queue at risk
262.8 and LU 349 Miami is #2, both substantially on this flag. LU 20 has one junk
statement plus two clean year-round ones and is fine. The top of the queue I am about
to work by hand is mis-ordered.

Set the flag only when the gate actually changed the outcome: the local has at least
one `type=rolling` statement classifying as `none` **and** has no surviving rolling
evidence. Add a separate, unweighted-or-lightly-weighted flag
`has_mixed_quality_statements` for the LU 20 case, because it is worth a glance but
it is not a risk.

## Task 5: re-derive `complete_lus`

15 of the 120 in `raw/scrape/complete_lus.json` now compute to `unknown`, so the
membership list is stale, as flagged in round 2.

Do not edit the JSON. Write `out/complete_lus_derived.csv` computed from current
state, with the criteria as explicit named booleans in the code:

- has a non-empty `application_url`
- `computed_status` not in (`unknown`, `conflicting`)

Columns: `local_union_id`, `lu_number`, `has_application_url`, `has_resolved_status`,
`is_complete`, `in_legacy_complete_lus`, `delta` (`added` / `dropped` / `unchanged`).

Report the counts three ways: legacy 120, newly derived, and the add/drop lists with
city and population. Do not change what `build_shippable.py` consumes yet, I want to
see the delta before the definition moves.

## Task 6: rebuild worklist and shippable

Re-run `build_verify_worklist.py` and `build_shippable.py`. Additions to the worklist:

- `next_open_date` and `window_precision_note` columns
- `has_mixed_quality_statements` in the flag vocabulary
- new flag `inferred_window_status` for any local whose status came from task 3
  resolution rather than a stated date. I need to be able to see at a glance which
  statuses rest on a pattern I inferred.

Confirm `shippable.csv` row and local counts, and explain any movement off
26,459 / 120.

## Task 7: `out/round3_status_diff.csv`

Every local whose `computed_status`, `status_confidence`, or `intake_pattern` changed
between the round 2 committed state and now. Columns: `local_union_id`, `lu_number`,
`charter_city`, `population_current_served_inside`, `status_before`, `status_after`,
`confidence_before`, `confidence_after`, `intake_pattern_before`,
`intake_pattern_after`, `which_task_caused_it`, `evidence_quote` (300), `source_url`.

Reconstruct the before-state by checking out the round 2 version of the relevant files
into a temp path, or by `git stash`-free read of the blob at `f40049f`. Do not guess
the before values from memory.

This file is how I audit the round. Sort by population descending.

## Task 8: verification, do not skip

1. Full test suite, paste the output. Every round 1 and round 2 test must still pass.
2. Confirm `build_window_label_audit.py` output is unchanged after the task 2 refactor.
3. Independently recount the displayable set (real status, confidence not `low`, zero
   risk flags) and separately the **actionable-today** set (`open` or `rolling`, same
   filters). Round 2 was 21 and 6. Report both new numbers.
4. Spot-check five locals that changed status in task 7 by reading their
   `evidence_quote` and `source_url` from the CSVs only, and state whether the new
   status is defensible from the quote alone. Do not fetch the pages.
5. Confirm no file under `raw/` was written and no network call was made.

## Task 9: report

Short and factual. Per task: what changed, the proving count or test output, the
commit. Then:

1. Final status distribution, 242 and 120.
2. Displayable count and actionable-today count, before and after this round.
3. How many locals now carry a `next_open_date`, and the 10 soonest with city and
   population. This is my lead-capture inventory, I want to see it.
4. The top 15 risk-sorted worklist rows after the flag fix.
5. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Re-extraction. The label defects from rounds 2 and 3 stay audited, not fixed. That
  costs money and it is my call.
- LU 43, 106, 306, 257 (no extraction). Note that LU 349 **does** have extraction
  despite being on my original defect list, so that list is stale. Do not act on it.
- The 26 locals with no `application_url`.
- Trademark, domains, website, app, prep content.
