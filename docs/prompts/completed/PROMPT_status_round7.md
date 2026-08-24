# Claude Code task: status pipeline, round 7 (two surgical fixes)

Working dir is this repo (`~/ibew`). Zero paid API cost, zero network, no
re-extraction. Small round: two defects, both introduced or exposed by round 6.

Round 6 is committed (`a7d5866`, `caf4bba`, `ebd3fe6`). `compute_status.py` has 89
passing tests, `TODAY = 2026-08-10` in the test class. Keep that constant.

## Concurrency

If the wage agent (`PROMPT_wages_round1.md`) is still running, the same ownership split
applies: you own `compute_status.py`, `statement_evidence.py`, `window_rules.py`, and
`out/round7_*.csv`. You own git in this tree, prefix commits with `status:`. Do **not**
touch page templates, build scripts, build output, or anything under `out/wage_*`. Do
**not** rebuild the site or the data bundle; Andrew does that once at the end.

If the wage agent has finished, the ownership rules still stand for this round. Do not
rebuild.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction. No network.**
- **Do not run any `pass*.py` script.** **Never write `out/extraction_v2.csv`.**
- Do not read `raw/`.
- Andrew is not available. Log blockers to `out/round7_blockers.csv` and continue.
- Every one of the 89 existing tests must still pass. If one fails, do not edit it.
  Stop, log it, and report.

---

## Task 1: recurring windows count as dated evidence

**This is a spec error in round 6, not an implementation error. The rule was written as
"every dated *absolute* window has closed" and it should have said "every resolvable
dated window".**

Round 6 task 1 correctly stopped undated prose from outranking expired dated windows.
But the "all windows closed" test only inspects `precision == 'absolute'` windows, so a
record whose *recurring* window is open today gets pushed to `expired_data` anyway.

### LU 613 Atlanta, 7,903,227 people, the second-largest local in the file

```
window 1  precision=absolute   open=2026-02-01  close=2026-03-31        <-- expired
window 2  precision=recurring  open_month=8 open_day=1
                               close_month=8 close_day=31
          is_recurring_annual=false
          relative_description "August 1st - August 31st"
          evidence_quote "Apprenticeship Program Applications Now OPEN! August 1st - August 31st"
          is_suspect_window -> (False, '')
statement [open] eff=None  "Apprenticeship Program Applications Now OPEN!"
```

`TODAY` is inside August 1 to August 31. **Applications in Atlanta are open.** Round 6
returns `expired_data`.

Note also that the `open` statement is not independent vague prose: it is the first half
of the same sentence as the window's `evidence_quote`. The window carries the dates.
Round 6 treated the two as conflicting when they agree.

Before round 6 this local returned `open` for weak reasons. It now returns the wrong
answer, which is worse. The direction matters: this tells 7.9 million people they cannot
apply during the one month of the year they can.

### The fix

The precedence test from round 6 task 1 must consider **all resolvable dated evidence**,
not only absolute windows:

- absolute windows with an `open_date`
- recurring windows that survive `is_suspect_window` and resolve under the round 3
  month/day logic, including the year-wrap case

If **any** resolvable window contains `TODAY`, the record is open and the round 6 rule
must not fire. Only when every resolvable window has closed does undated prose lose and
the result become `expired_data`.

Reuse the round 3 recurring-resolution code rather than reimplementing the month/day and
wrap handling. If it is currently inline in `compute_status`, extract it to a named
function both call sites use, so this cannot drift again.

`LU 613` must come out `open`, confidence `medium` (inferred from a pattern, never
`high`, per round 3), `inferred_window_status` true.

### Do not change these two

I checked them and both are defensible as they stand:

- **LU 490 Dover** (1,541,118), recurring June 1 to May 20 which contains today, but
  computed `closed_pending`. Its prose says intake begins "August of 2027", which
  genuinely conflicts with the window. Round 5 demoted it on the future start date and
  that call stands. Leave it.
- **LU 12 Pueblo** (367,985), live recurring window, computed `rolling`. Not a
  contradiction. Leave it.

If your fix moves either of them, the rule is too broad. Fix the rule, not the test.

## Task 2: an open-ended open date is not a close date

**LU 567 Portland** returns `next_open_date` **and** `next_close_date` both set to
`2026-11-02`:

```
window  precision=absolute  open_date=2026-11-02  close_date=""
statement [closed]    eff=None        "Applications for IBEW 567 Apprenticeship are
                                       closed they will reopen November 2nd, 2026."
statement [reopening] eff=2026-11-02   (same sentence)
```

The window is open-ended: it has a start and no end. Its `open_date` is being assigned
to `next_close_date` as well as `next_open_date`. On the page that renders as "opens
November 2, closes November 2".

`next_close_date` may only be populated from a genuine end bound: an absolute window's
`close_date`, a resolved recurring window's computed end, or an embedded date that
`statement_evidence` classified as a closing bound. Never from an `open_date`, and never
from a reopen announcement.

This is the same family as the LU 466 Charleston fix in round 5, so check whether that
fix covered only the statement path and left the window path alone. Say what you find.

Add an assertion or a test that no record can ever emit `next_open_date` equal to
`next_close_date`. Currently exactly one local does; after the fix it must be zero.

## Task 3: tests

Extend the existing class, keep `TODAY = 2026-08-10`, all 89 must still pass. Fixtures
from **real** JSON in `extraction_v2.csv`.

- LU 613 → `open` / medium, `inferred_window_status` true
- LU 613's continuing-education statement → still rejected `program_mismatch`
  (round 6 guard)
- LU 538 Danville → still `expired_data`. It has only absolute windows, both expired,
  so task 1 must not rescue it. This is the pair that proves the fix is narrow.
- LU 567 → `closed_pending` / high, `next_open_date` 2026-11-02,
  `next_close_date` empty
- LU 490 Dover → unchanged `closed_pending`
- LU 12 Pueblo → unchanged `rolling`
- LU 130 New Orleans → unchanged `closed`, `next_open` 2027-01-01 (round 6 guard)
- LU 1340 → unchanged `closed_pending` / high, `next_open` 2026-12-01
- LU 292 Minneapolis → unchanged `conflicting` (round 6 guard)
- LU 26 DC → unchanged `expired_data` (round 5 guard)
- A synthetic record: undated `open` prose + one expired absolute window + one recurring
  window that is **not** current → `expired_data`. Proves task 1 checks currency, not
  merely the presence of a recurring window.
- A synthetic record: no `next_open`/`next_close` collision across all 242 real records

## Task 4: code comment on the LU 292 compromise

Round 6 kept rule 1 (`conflicting`) reading raw ungated `statement_type` labels, to
avoid a demote-only violation on LU 292. That was the right call under the constraint,
but it leaves a known inconsistency: LU 292's "Pre-apprentice hiring is frozen"
statement is about hiring rather than intake, your own gate correctly rejects it as
`no_application_subject`, and yet it still counts as conflict evidence because rule 1
does not consult the gate.

Write that down in a comment above rule 1: what the compromise is, why it exists, which
local it protects, and what would need to change to remove it. Do not change the
behaviour this round. I want the next person reading this to understand it is deliberate
rather than an oversight.

## Task 5: diff and verify. No rebuild.

1. `out/round7_status_diff.csv`, before-state loaded from the git blob at `ebd3fe6`,
   using the same sandboxed `sys.modules` approach you built in round 6. Columns as
   round 6, plus `next_close_before`, `next_close_after`, `inferred_window_status`.
2. Full suite, paste the output.
3. Run the 242-record loop, print the status distribution, and confirm every record
   computes without raising. Expected movement is small: LU 613 into `open`, nothing
   else. Report anything else that moves.
4. Confirm zero records where `next_open_date == next_close_date`.
5. List every file you modified. Confirm you touched nothing outside your ownership
   list, did not rebuild, and made no network call.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Status distribution across 242, before and after.
2. Every local that moved, with population.
3. Whether the round 5 LU 466 fix covered the statement path only, and what the window
   path was doing.
4. Confirmation that LU 538, LU 490 and LU 12 all held still.
5. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Anything the wage agent owns.
- Rebuilding the site or the bundle.
- Changing the LU 292 rule 1 behaviour. Comment only, this round.
- Re-extraction, hosting, domain, email backend, trademark.
