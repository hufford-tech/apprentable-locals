# Claude Code task: status pipeline, round 6 (dated evidence wins)

Working dir is this repo (`~/ibew`). Zero paid API cost, zero network, no
re-extraction.

**This prompt runs CONCURRENTLY with `PROMPT_wages_round1.md` in a separate agent.
File ownership is strict. Read the ownership section before touching anything.**

## FILE OWNERSHIP, non-negotiable

You own, and may modify:

- `compute_status.py`
- `statement_evidence.py`
- `window_rules.py`
- `out/round6_status_diff.csv` (new)
- `out/statement_dedup_audit.csv` (new)
- any new test file you add for the above

You must **NOT** touch, for any reason:

- `page_template.html`, `site/local*` templates, `site/local.css`, `site/js/*`
- `build_page.py`, `build_local_pages.py`, `build_frontend_data.py`
- `wage_rules.py`, `test_wage_rules.py`, `out/wage_*.csv`
- `ibew_finder.html`, `site/index.html`, `site/local/*.html`, `out/frontend_data.json`

**Do not rebuild the site or the data bundle.** Not once, not at the end. The wage
agent owns every build step and Andrew runs the final rebuild after we both finish. If
you rebuild, you will overwrite the other agent's work with a stale bundle.

Your deliverable is changed Python plus two CSVs. Nothing else.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction. No network.**
- **Do not run any `pass*.py` script.** **Never write `out/extraction_v2.csv`.**
- Do not read `raw/`. Nothing here needs it.
- Andrew is not available. Log blockers to `out/round6_blockers.csv` and continue.
- One commit per task, and prefix every commit message with `status:` so the two
  concurrent agents' history stays legible.
- **Demote-only, with one exception.** No change may turn a negative or unknown status
  into a confident positive. Task 3 is the single permitted promotion, `unknown` to
  `closed`, which is a demotion in user terms.

## State you do not need to rediscover

- `compute_status.py`: 75 passing tests, `TODAY = 2026-08-10` in the test class. Keep it.
- 242 distribution: unknown 113, rolling 61, open 23, closed_pending 20, closed 11,
  conflicting 10, expired_data 4.
- Round 5 built `statement_evidence.admit_statement()` and routed **only**
  `statement_type == 'open'` through it. `closed` and `reopening` still read their raw
  labels. A fully label-blind rewrite was attempted and reverted after regressions on
  LU 567, LU 1340 and LU 130, logged in `out/round5_blockers.csv`.

---

## Task 1: dated windows beat undated prose

**The worst live defect in the dataset.** An undated `open` statement outranks an
expired dated window on the same record.

**LU 613 Atlanta, 7,903,227 people, the second-largest local in the file.**
Currently `open` / medium:

```
[open]   eff=None  "Apprenticeship Program Applications Now OPEN!"
window   absolute  open=2026-02-01  close=2026-03-31     <-- closed 4.5 months ago
window   recurring om=8 cm=8 annual=False
```

**LU 538 Danville**, currently `open` / medium, identical shape:

```
[open]   eff=None  "The JATC will be taking applications on the following days in 2026"
window   absolute  open=2026-03-30  close=2026-04-03     <-- passed
window   absolute  open=2026-04-06  close=2026-04-10     <-- passed
```

Note what LU 538's sentence actually is: a **header introducing the window list**, not
an independent claim of current availability. "on the following days" is literally
pointing at the dates below it. Treating it as standalone evidence is the error.

**Rule.** An admitted `asserts == 'open'` statement carrying no date of its own cannot
produce `open` when the record also holds one or more dated absolute windows and
**every** one of them has closed. In that case the windows are the better evidence and
the result is `expired_data`, confidence `medium`.

Generalise it rather than special-casing `open`: dated evidence outranks undated prose
whenever the two conflict, for every `asserts` value. Undated prose may still resolve a
record that has no usable dated evidence, which is what keeps the 16 legitimate
prose-only `open` locals from round 5 intact.

Regression guards that must not move: LU 68 Denver, LU 570 Tucson, LU 38 Cleveland,
LU 236 Albany, LU 112 Kennewick, LU 153 South Bend, LU 110 St. Paul, LU 558 Sheffield,
LU 456 New Brunswick, LU 34 Peoria, LU 575 Portsmouth, LU 673 Painesville,
LU 270 Oak Ridge, LU 972 Marietta. None of those has a conflicting expired window.

## Task 2: finish the label-blind gate for `closed` and `reopening`

Round 5 gated `open` only, and LU 613 proves the cost. Its second statement:

```
[closed] eff=None  "Journeyman Wireman Continuing Education CURRENTLY CLOSED"
```

That is **journeyman continuing education**, not the inside-wireman apprenticeship.
Round 5's `program_mismatch` rule would reject it, but `closed` statements never reach
the gate, so it sits in the record as apprenticeship evidence.

Route `closed` and `reopening` through `admit_statement` too, so all five reject
reasons (`negative_context` is wage-side, ignore it; here it is
`no_application_subject`, `method_only`, `cta_only`, `office_hours`,
`program_mismatch`) apply regardless of label.

Round 5 reverted this because of regressions on LU 567 and LU 1340. Both are currently
**correct** and must stay correct:

```
LU 567 Portland   -> closed_pending / high, next_open 2026-11-02
  [closed]    eff=None        "Applications for IBEW 567 Apprenticeship are closed
                               they will reopen November 2nd, 2026."
  [reopening] eff=2026-11-02  (the same sentence, emitted twice)
  window absolute open=2026-11-02 close=

LU 1340 Newport News -> closed_pending / high, next_open 2026-12-01
  [reopening] eff=2026-12-01  "THE DEADLINE FOR THE UPCOMING SCHOOL YEAR HAS PASSED,
                               APPLICATIONS FOR THE 2027 SCHOOL YEAR WILL BE
                               AVAILABLE DECEMBER 1, 2026"
  window recurring om=12 cm=4 annual=True
  window absolute  open=2026-12-01 close=
```

Round 5's note says these suffered "date misfiling". Diagnose why before changing
anything. My read is that gating `reopening` dropped the statement that carried the
`next_open_date`, so the date fell back to a window or vanished. If that is the cause,
the fix is that an admitted statement's date must survive independently of whether the
statement originates the status. Write down what you actually find.

## Task 3: LU 130, and I disagree with the round 5 blocker note

```
LU 130 New Orleans, 1,233,922 people -> currently unknown / low
  [closed]    eff=None  "APPLICATIONS FOR THE 2026-2027 SCHOOL YEAR ARE NOW CLOSED."
  [reopening] eff=None  "Please contact the office in January 2027 for information
                         regarding the 2027-2028 school year."
  window precision=none
```

`out/round5_blockers.csv` records the label-blind version as having "wrongly promoted
unknown to closed" here. I think `closed` is the **right** answer and `unknown` is the
bug.

This is exactly LU 520 Austin's shape from round 4: a closure scoped to a past cohort,
with a successor intake that is explicitly future rather than currently open. Round 4's
rule says that stays `closed`. LU 130 should be `closed`, and "January 2027" should
yield `next_open_date` 2027-01-01 with `date_precision_note = 'month_inferred'`.

Implement that. If you conclude I am wrong after reading the record, do not implement
it, and put your reasoning in the report. Do not split the difference.

## Task 4: de-duplicate statements

LU 567 emits **one sentence twice**, as `closed` and as `reopening`. Harmless there,
but two copies of one sentence look like two independent pieces of evidence, and the
round 2 conflicting rule and the round 5 corroboration logic both count statements.

Add de-duplication keyed on normalised `verbatim_text` (collapse whitespace, strip
punctuation, lowercase). Where duplicates differ only by `statement_type`, keep one
record carrying **both** derived assertions rather than two records. Emit
`out/statement_dedup_audit.csv`: `local_union_id`, `lu_number`, `normalised_text`,
`duplicate_count`, `statement_types`, `kept_asserts`, `affected_status`.

Report how many locals had duplicates and whether any status changed as a result.
I expect this to be cosmetic. If it moves more than 5 locals, tell me before I trust it.

## Task 5: tests

Extend the existing class, keep `TODAY = 2026-08-10`, all 75 existing tests must pass.
Fixtures from **real** JSON in `extraction_v2.csv`.

- LU 613 → `expired_data`, and the Journeyman Continuing Ed statement rejected
  `program_mismatch`
- LU 538 → `expired_data`
- LU 130 → `closed`, `next_open_date` 2027-01-01, note `month_inferred`
- LU 567 → unchanged `closed_pending` / high, `next_open` 2026-11-02, and the duplicate
  sentence counted once
- LU 1340 → unchanged `closed_pending` / high, `next_open` 2026-12-01
- LU 520 Austin, LU 150 Waukegan → unchanged, the round 4 guards
- LU 26 DC → still `expired_data`, the round 5 guard
- All 14 prose-only `open` guards from task 1 → unchanged
- A synthetic record with an undated `open` statement **and** a currently-open dated
  window → stays `open`. Task 1's rule fires only when every dated window has closed.

## Task 6: diff and verify. No rebuild.

1. `out/round6_status_diff.csv`, before-state from the git blob at the commit you
   started from, not from memory. Columns: `local_union_id`, `lu_number`,
   `charter_city`, `population_current_served_inside`, `status_before`, `status_after`,
   `confidence_before`, `confidence_after`, `next_open_before`, `next_open_after`,
   `which_task_caused_it`, `evidence_quote` (300), `source_url`. Sort by population
   descending.
2. Full `compute_status.py` suite, paste the output.
3. Run the 242-record loop and confirm every record still computes without raising.
4. Confirm you did **not** write any file outside your ownership list. List every file
   you modified.
5. Confirm no network call, `raw/` untouched, `extraction_v2.csv` untouched.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Status distribution across 242, before and after.
2. Every local that moved, with population and cause. LU 613 Atlanta at 7.9M is the
   one I care most about.
3. Your actual diagnosis of the LU 567 / LU 1340 date misfiling, and whether task 2
   could be completed without reintroducing it.
4. Whether you agree with me on LU 130, and why.
5. Duplicate-statement count from task 4 and whether any status moved.
6. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Anything the wage agent owns. See the ownership section.
- Rebuilding the site or the bundle. Andrew does that once, after both agents finish.
- Re-extraction, hosting, domain, email backend, trademark.
