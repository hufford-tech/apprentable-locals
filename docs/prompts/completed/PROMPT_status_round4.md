# Claude Code task: status pipeline, round 4 (scope and statement coverage)

Working dir is this repo (`~/ibew`). Zero paid API cost, zero network, no
re-extraction. Everything below is deterministic Python over files on disk.

Rounds 1 through 3 and the frontend round are committed. `compute_status.py` has 38
passing tests with `TODAY = 2026-08-10` in the test class. Keep that constant.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction. No network.**
- **Do not run any `pass*.py` script.** **Never write `out/extraction_v2.csv`.**
- Do not read `raw/` this round. Nothing here needs it.
- I am not available. Log blockers to `out/round4_blockers.csv` and continue.
- One commit per task. Full suite green before each commit.
- Every fix must be **demote-safe**: when the evidence is genuinely ambiguous, land on
  `unknown` or `conflicting`, never on a confident positive. Showing someone "apply
  now" for a closed program is the only unrecoverable error here.

## Why this round exists

The scoped-closure audit flagged 22 of 53 `closed` statements. Most are false
positives (past window logs, "until further notice"). But pulling the underlying
records surfaced worse problems that the audit was not looking for. **Read all six
records below before writing code.** They are the spec.

### LU 112 Kennewick — currently `unknown` / low. Three separate bugs.

```
stmt[open]      eff=None        "Applications Are Currently Open"
stmt[closed]    eff=2026-10-01  "applications are closing October 1, 2026 and will be
                                 closed through the remaining of 2026 but will open
                                 again in 2027"
stmt[closed]    eff=2026-10-01  "After October 1st, 2026 we will only be accepting
                                 re-interview applications..."
stmt[reopening] eff=None        "APPLICATIONS WILL BE REOPEN IN 2027."
stmt[unknown]   eff=None        "Applications are AVAILABLE as needed throughout the year..."
win absolute close=2026-10-01
days_since_evidence: -50
```

The page says, in plain English, that applications are open right now and close on
October 1. Today is August 10. This returns `unknown`.

1. **`statement_type == 'open'` is never consumed anywhere in `compute_status`.** Grep
   it. The function branches on rolling, closed, and reopening only. An entire
   statement type is silently discarded.
2. **A `closed` statement with a future `stated_effective_date` means "will close,"
   not "is closed."** The code treats every closed statement as present tense.
3. **`days_since_evidence` is -50.** Negative, because the most recent dated evidence
   is in the future. That value then feeds the confidence cap from round 2, where the
   comparisons are written assuming a non-negative number.

### LU 728 Ft. Lauderdale — currently `open` / high. Overconfident.

```
stmt[closed]    eff=2026-03-09  "As of March 9, 2026, online applications are closed."
stmt[reopening] eff=2026-07-01  "We will reopen the applications on July 1, 2026."
win absolute open=2026-07-01 close=(none)
```

Rule 2 sees today past `open_date` with no `close_date` and returns `open` / `high`
forever. An open-ended window is a weak claim that decays. The competitor publishes
"Watching" for this local, which is the more honest read, and your own audit
independently flagged it.

### LU 313 Wilmington — currently `closed` / high. Wrong.

```
stmt[closed] eff=None  "No applications will be accepted in September 2026."
```

A future-scoped exclusion. It implies applications *are* accepted now, in August.

### LU 488 Bridgeport — currently `closed` / medium. Wrong.

```
stmt[closed]  eff=None  "SELECTION OF APPLICANTS FOR CLASSES BEGINNING SEPTEMBER OF
                         2026 HAS CLOSED."
stmt[unknown] eff=None  "APPLICATIONS RECEIVED WILL BE FOR CONSIDERATION FOR CLASSES
                         BEGINNING SEPTEMBER 2027."
```

The closure is scoped to the 2026 cohort, and a second statement says applications
received now go to the 2027 cohort. They are accepting. Note the decisive statement is
typed `unknown`, another type the function discards.

### LU 150 Waukegan — currently `closed_pending` / high, `next_open` 2026-10-01. **Correct.**

```
stmt[closed]    eff=None        "Applications for the 2026 Program are now CLOSED"
stmt[reopening] eff=2026-10-01  "Applications will reopen on October 1, 2026"
```

Cohort-scoped closure with an explicit reopen date. Must not change. Regression guard.

### LU 520 Austin — currently `closed` / medium. **Correct.**

```
stmt[closed] eff=None  "The Deadline to Submit an Application for September 2026
                        Classes has passed...when we begin accepting applications for
                        the next term we will announce it here!"
```

Cohort-scoped, but the successor intake is explicitly *not* open yet. Must not change.
This is the pair to LU 488 and the distinction between them is the whole task.

---

## Task 1: fix `days_since_evidence`

Split the concept. Evidence recency should measure how old the *most recent past*
evidence is, and must never go negative.

- `days_since_evidence` = today minus the most recent dated evidence **that is not in
  the future**. `None` when there is no past dated evidence.
- Add `days_until_next_event` = the soonest future dated evidence minus today, or
  `None`. A future date is real information, it is just not recency.
- Audit every comparison against `days_since_evidence` in the codebase, especially the
  round 2 confidence cap, and confirm each still behaves with `None`.

Tests: a record with only future dates yields `days_since_evidence = None` and a
positive `days_until_next_event`. LU 112 and LU 150 both currently report -50.

## Task 2: consume `open` statements

Add handling for `statement_type == 'open'`. Placement matters: it must lose to a
contradicting present-tense closure and must not override a dated window.

Proposed ordering, argue in a comment if you disagree after reading the records:

1. conflicting (existing)
2. rolling (existing)
3. dated absolute window containing today (existing)
4. **`open` statement with no contradicting present-tense closed statement → `open`,
   confidence `medium`.** Never `high`. A prose claim is weaker than a dated window.
5. everything else as today

An `open` statement alongside a closed statement whose effective date is in the future
is **not** a contradiction, it is the normal "open now, closing soon" case. That is
exactly LU 112, which should land on `open` / medium with `next_close_date`
2026-10-01. Add `next_close_date` to the output, it is the urgency hook and it is the
mirror of `next_open_date`.

## Task 3: tense-aware closed statements

A `closed` statement with `stated_effective_date` in the future announces a future
closure. It must not close the local today. It should populate `next_close_date` and
otherwise stand aside.

A `closed` statement with a past or absent effective date behaves as it does now,
subject to task 4.

## Task 4: three-way scope classification

Add `classify_closure_scope(text, today)` returning one of:

- `future_period` — the closure is confined to a period that has not started, or to a
  named future month or date range. Implies currently open. LU 313.
- `past_cohort` — the closure names a specific class, cohort, term, or program year
  that has already closed. Says nothing about current intake on its own.
- `unscoped` — a plain closure. LU 48 Portland "closed for all applications until
  further notice", LU 46 Seattle "temporarily stopped accepting new applications".

Explicit traps, all currently flagged by the keyword audit and all `unscoped`:

- "until further notice", "indefinitely", "temporarily" are **not** scope limiters.
  They describe duration, not scope.
- A past window log such as LU 11's "January 5th, 2026 (APPLICATION WINDOW CLOSED)" is
  a historical record, not a scoped closure.
- LU 48 lists Inside, Limited Energy, and Residential each as closed. The presence of a
  named non-inside program does not make it scoped when the inside program is also
  named closed.

Wire it in:

- `future_period` → the closure does not apply today. Populate `next_close_date` when
  a date is derivable. Fall through to the other rules.
- `past_cohort` → the closure does not by itself close the local. Resolve using the
  rest of the record:
  - a successor intake is described as accepting (LU 488) → not closed
  - a successor intake is explicitly future or unannounced (LU 520) → stays closed
  - nothing resolves it → `unknown`, not `closed`
- `unscoped` → unchanged.

**LU 520 must not move and LU 150 must not move.** If either does, the classifier is
too aggressive. Fix the classifier, not the test.

## Task 5: `unknown`-typed statements as corroboration only

LU 488's decisive sentence is typed `unknown`. These are currently discarded entirely.

Let them **corroborate but never originate**. An `unknown` statement may resolve a
`past_cohort` ambiguity when it names a successor cohort as accepting, and it may never
by itself produce `open`, `rolling`, or `closed`. Add a `corroborated_by_unknown_stmt`
boolean to the output so any status resting on one is visible and auditable.

## Task 6: open-ended windows decay

An absolute window with an `open_date` and no `close_date` currently returns
`open` / `high` indefinitely. Add decay measured from `open_date`:

- within 60 days → `open` / `high`
- 60 to 180 days → `open` / `medium`
- past 180 days → `expired_data` / `low`, on the reasoning that a window nobody closed
  and nobody updated is stale rather than open

LU 728 opened 2026-07-01, so at `TODAY` it is 40 days in and stays `open` / `high`.
Add a fixture at day 200 that decays it. Tune the thresholds if you can argue for
better ones from the data, and record the reasoning in a comment.

## Task 7: tests

Extend the existing class, keep `TODAY = 2026-08-10`, all 38 existing tests must pass.
Build fixtures from the **real** JSON in `extraction_v2.csv`, not invented strings.

Required:

- LU 112 → `open` / medium, `next_close_date` 2026-10-01, `days_since_evidence` None,
  `days_until_next_event` 52
- LU 728 → `open` / high today; same record at day 200 → `expired_data` / low
- LU 313 → not `closed`
- LU 488 → not `closed`, `corroborated_by_unknown_stmt` true
- LU 150 → unchanged: `closed_pending` / high, `next_open` 2026-10-01
- LU 520 → unchanged: `closed` / medium
- LU 48, LU 46, LU 11 → unchanged, `unscoped`
- `classify_closure_scope` units: at least 5 per category plus every trap above

## Task 8: diff, rebuild, verify

1. `out/round4_status_diff.csv`: every local whose status, confidence, or any new field
   changed. Columns `local_union_id`, `lu_number`, `charter_city`,
   `population_current_served_inside`, `status_before`, `status_after`,
   `confidence_before`, `confidence_after`, `next_open_before/after`,
   `next_close_date`, `which_task_caused_it`, `evidence_quote` (300), `source_url`.
   Reconstruct the before-state from the git blob at the current HEAD, not from memory.
   Sort by population descending.
2. Full test suite, paste output.
3. Rebuild `out/frontend_data.json`, `ibew_finder.html` (both `--single` and `--lean`),
   and the 244 static pages. Surface `next_close_date` in the status band and on the
   local pages, governed by the existing `STATUS_DISPLAY` flag. Copy for the open case
   should read like "Open now, closes October 1, 2026."
4. Re-verify: ZIP index mismatches still zero, the 12 sample ZIPs still resolve, 244
   unique slugs, no dangling links, both flag variants still strip clean, 22 node tests
   still pass.
5. Confirm no network call and no write under `raw/` or to `extraction_v2.csv`.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Status distribution across 242 and across the site, before and after.
2. Every local that moved, grouped by which task moved it, with population.
3. Locals now carrying `next_close_date`, and the five soonest. These are the highest
   urgency leads in the dataset.
4. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Re-extraction. Everything here is fixable in `compute_status`.
- Displaying wage data. Still candidates only.
- Hosting, domain, email backend, trademark.
