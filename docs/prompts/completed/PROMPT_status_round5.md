# Claude Code task: status pipeline, round 5 (one gate for all statements)

Working dir is this repo (`~/ibew`). Zero paid API cost, zero network, no
re-extraction. Deterministic Python over files on disk.

Round 4 is committed (`fde1989`, `3d65b15`, `c37c336`, `76e88b8`).
`compute_status.py` has 50 passing tests with `TODAY = 2026-08-10`. Keep that constant.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction. No network.**
- **Do not run any `pass*.py` script.** **Never write `out/extraction_v2.csv`.**
- Do not read `raw/`. Nothing here needs it.
- I am not available. Log blockers to `out/round5_blockers.csv` and continue.
- One commit per task. Full suite green before each commit.
- **Demote-only.** No change in this round may turn a negative or unknown status into
  a positive one, or raise any confidence level. Every rule here either downgrades or
  leaves things alone. If you find yourself writing a promotion, stop and log it.

## Why this round exists, read before writing code

Round 2 fixed `rolling` statements by requiring an application subject plus temporal
language and ignoring method-only text. Round 4 wired in `statement_type == 'open'`,
which had been dead code, **without an equivalent gate**. The identical defect
reappeared in the new type. `open` went from 8 locals to 35, and 27 of those 35 rest
on a prose statement with no dated window. Roughly half of the 27 are wrong.

This is the fourth consecutive round where the previous round's fix failed to
generalize to the next statement type. That pattern is the actual defect. So this
round does not add a third per-type gate. It builds **one admissibility gate that
every statement passes through regardless of its `statement_type` label**, and makes
each branch consume only admitted statements.

`statement_type` is an unreliable LLM label. Treat it as a hint about intent, never as
evidence about content.

### The failing records. These are the spec.

**LU 26 Washington DC, 8,223,617 people, the largest local in the file.**
Currently `open` / medium on:

> "Applications currently being accepted are for the Class of 2030. The deadline to
> apply is March 31, **2025**."

A deadline sixteen months in the past. `stated_effective_date` is null, so
`compute_status` never sees the date that contradicts the status.

**Same family, all currently `open`:**

- LU 490 Dover, 1,541,118: "accepting applications for the 2027-2028 school year
  **starting August of 2027**" (starts in a year)
- LU 1253 Augusta, 461,832: "Applications are due **March 31, 2026**" (four months past)
- LU 607 Shamokin, 300,915: "Apply in person or online **until April 10th, 2026**"
  (four months past)
- LU 234 Castroville, 767,816: "To be eligible for the next aptitude test in
  **February 2027**, applications..." (forward-looking, ambiguous)

**Method-only, the round 2 defect in a new type. All currently `open`:**

- LU 494 Milwaukee, 1,856,989: "If you meet the minimum qualifications you may apply
  by following this link CLICK HERE" (four near-identical copies)
- LU 1205 Gainesville, 2,493,847: "applications can be obtained in person at
  Gainesville Electrical Joint Apprenticeship and Trai..."
- LU 16 Evansville, 530,567: "Online applications for both the inside and residential
  program are available. Click on the Apply Online"
- LU 163 Wilkes-Barre, 323,408: "Start your application to the IBEW Local 163 JATC
  Apprenticeship Program today!" (marketing CTA, not a status)
- LU 601 Champaign-Urbana, 411,138: "Summer Hours for applications: Wednesdays from
  12:30 pm - 3:30 pm" (office hours; `is_suspect_window` already rejects this exact
  text in the windows array, and it walked in through the statements array instead)

**Program mismatch:**

- LU 229 York, 437,782: the "Now Accepting Applications" statement is for the
  **Construction Wireman / Construction Electrician** program. Its inside-wireman
  statement is method-only ("you must apply online"). CW/CE is not the inside
  apprenticeship.

**Must not move. Regression guards.** These are legitimately open and any gate that
demotes them is too aggressive:

LU 68 Denver "Applications now open." · LU 570 Tucson "We are now accepting
Applications online." · LU 38 Cleveland "The JATC is now accepting applications
on-line, 24/7." · LU 236 Albany "Applications for apprenticeship are now being
accepted." · LU 112 Kennewick "Applications Are Currently Open" · LU 153 South Bend
"Applications Are OPEN" · LU 110 St. Paul · LU 558 Sheffield · LU 456 New Brunswick ·
LU 34 Peoria · LU 575 Portsmouth · LU 673 Painesville · LU 270 Oak Ridge ·
LU 972 Marietta

Also unmoved: LU 150 Waukegan, LU 520 Austin, LU 48 Portland, LU 46 Seattle, LU 11
Los Angeles, and every round 1 through 4 fixture.

---

## Task 1: `statement_evidence.py`, one admissibility gate

New module. Every statement, every type, passes through this before any branch reads
it. `compute_status` must not touch a raw statement dict again.

```
admit_statement(stmt, today) -> {
    admissible: bool,
    reject_reason: str,          # '' when admissible
    asserts: str,               # 'open'|'closed'|'rolling'|'reopening'|'none'
    embedded_dates: [date],     # dates lifted from verbatim_text
    tense: str,                 # 'past'|'present'|'future'|'unknown'
    scope: str,                 # from round 4's classify_closure_scope, '' if n/a
    program: str,               # 'inside'|'other'|'unspecified'
}
```

Rejection rules, all demote-only:

1. **No application subject** → reject `no_application_subject`. Reuse round 2's
   subject vocabulary (application, applicant, apply, accept applications, enroll,
   registration, sign up, intake, take applications). Do not duplicate the list,
   import it from wherever `classify_intake` keeps it.
2. **Method-only** → reject `method_only`. Text describes how to apply (online, portal,
   website, click, link, in person at an address, call the office, create an account,
   by mail) and asserts nothing about whether intake is happening. LU 494, 1205, 16.
3. **Marketing CTA with no state claim** → reject `cta_only`. Imperative
   encouragement ("start your application today", "apply now" with no temporal or
   status assertion). LU 163. Be careful: "Applications Are OPEN Apply NOW!!!" (LU 153)
   carries a state claim and must be admitted.
4. **Business or office hours** → reject `office_hours`. Clock times with no calendar
   date or month. LU 601. Import the predicate from `window_rules.py` rather than
   reimplementing it, since it already handles this shape.
5. **Program mismatch** → set `program='other'` and reject `program_mismatch` when the
   text names a non-inside program (residential, CW, CE, construction wireman,
   construction electrician, VDV, telecommunications, sound and communication, limited
   energy, lineman, outside) **and does not also name the inside program**. Naming
   inside alongside others keeps it admissible, which is what makes LU 48 Portland
   still correctly closed.

`asserts` is derived from the **text**, not from `statement_type`. Where the two
disagree, the text wins and the disagreement gets recorded (task 4).

## Task 2: embedded date extraction

The single highest-value fix. Lift dates out of `verbatim_text` into `embedded_dates`.

Parse at minimum: `March 31, 2025`, `March 31st, 2025`, `3/31/2025`, `2025-03-31`,
`April 10th, 2026`, bare `August of 2027` and `February 2027` (month plus year, no
day), and cohort years in `Class of 2030` / `2027-2028 school year`.

Distinguish a **deadline or bound** from a **cohort reference**. "The deadline to apply
is March 31, 2025" is a bound on intake. "Class of 2030" is the name of a cohort and
says nothing about when you can apply. Only bounds affect status.

Then, in the rule chain:

- An `asserts == 'open'` statement whose embedded bound has **passed** cannot produce
  `open`. Result is `expired_data` when nothing newer exists, else fall through.
  LU 26, LU 1253, LU 607.
- An `asserts == 'open'` statement whose embedded bound is **in the future** produces
  `open` and populates `next_close_date` from that bound.
- An `asserts == 'open'` statement whose start is **in the future** cannot produce
  `open`. It produces `closed_pending` with `next_open_date` from that start. LU 490.
- Month-plus-year with no day: treat as the last day of that month for a bound, the
  first day for a start, and set `date_precision_note = 'month_inferred'`.
- Ambiguous forward references that are neither a clean bound nor a start, like
  LU 234's aptitude-test eligibility, resolve to `unknown`, not `open`.

Add `embedded_date_conflict: bool` to the output, true whenever an admitted statement's
embedded date contradicts what its text asserts. That is the flag I want on the
verification worklist.

## Task 3: rewire `compute_status` to consume only admitted statements

Refactor so every branch filters through `admit_statement` and reads `asserts`, never
`statement_type`. Preserve round 1 through 4 semantics exactly for everything that is
not fixed above: the conflicting rule, the intake gate, tense-aware closures, scope
classification, unknown-corroboration, open-ended window decay, and the confidence cap.

Two carry-overs from round 4's report to fold in:

- **LU 400 / LU 701.** A bounded absolute window with an explicit **future**
  `close_date` is self-evidently current. Cap its confidence off `close_date`, not off
  `open_date` age. This restores `high` where the window is still running.
- **LU 466 Charleston.** A single closed statement that bundles "2026 PERIOD HAS
  CLOSED" with "NEXT PERIOD BEGINS JANUARY 4TH, 2027" is currently labelling that 2027
  date as `next_close_date`. A reopen announcement inside a closure statement is a
  `next_open_date`. Fix the assignment.

Add `admitted_statement_count` and `rejected_statement_count` to the output.

## Task 4: `out/statement_admissibility_audit.csv`

One row per statement across all 242 locals: `local_union_id`, `lu_number`,
`charter_city`, `population`, `statement_type` (the label), `asserts` (the derived
value), `label_disagrees`, `admissible`, `reject_reason`, `tense`, `scope`, `program`,
`embedded_dates`, `embedded_date_conflict`, `verbatim_text` (300), `source_url`.

Print counts by `reject_reason`, by `label_disagrees`, and the label-versus-asserts
confusion matrix. That matrix is the number I actually want out of this round: it tells
me how unreliable `statement_type` is across the whole corpus, which decides whether
re-extraction is worth paying for.

This supersedes `out/statement_label_audit.csv` from round 2. Leave the old file, note
the supersession in a comment.

## Task 5: tests

Extend the existing class, keep `TODAY = 2026-08-10`, all 50 existing tests must pass.
Fixtures from **real** JSON in `extraction_v2.csv`, never invented strings.

- LU 26 → not `open`. `expired_data` expected, `embedded_date_conflict` true
- LU 1253, LU 607 → not `open`
- LU 490 → `closed_pending`, `next_open_date` 2027-08-01, note `month_inferred`
- LU 234 → `unknown`
- LU 494, LU 1205, LU 16 → rejected `method_only`, status `unknown`
- LU 163 → rejected `cta_only`, status `unknown`
- LU 601 → rejected `office_hours`, status `unknown`
- LU 229 → rejected `program_mismatch` on the CW/CE statement, not `open`
- LU 153 → still `open`. "Applications Are OPEN Apply NOW!!!" must survive rule 3
- All 14 named regression guards → unchanged status and confidence
- LU 48 Portland → still `closed`, proving the program rule does not fire when inside
  is named among others
- LU 400, LU 701 → `open` / high restored
- LU 466 → 2027-01-04 lands in `next_open_date`, not `next_close_date`
- `admit_statement` units: at least 4 per reject reason
- Date parser units: every format listed in task 2, plus a cohort reference that must
  **not** be read as a bound

## Task 6: diff, rebuild, verify

1. `out/round5_status_diff.csv`, before-state from the git blob at `fde1989`, not from
   memory. Same columns as round 4 plus `embedded_date_conflict`,
   `rejected_statement_count`, `reject_reasons`.
2. Full suite, paste output.
3. Rebuild `out/frontend_data.json`, both finder builds, all 244 static pages.
4. Re-verify: ZIP mismatches zero, the 12 sample ZIPs resolve, 244 unique slugs, zero
   dangling links, both flag variants strip clean, 22 node tests pass.
5. Confirm no network, `raw/` untouched, `extraction_v2.csv` untouched.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Status distribution across 242 and across the site, before and after.
2. **The label-versus-`asserts` confusion matrix**, and the rejection count by reason.
3. Every local that moved, with population and reject reason.
4. Of the 35 locals currently `open`, how many survive. My estimate from reading the
   statements by hand was about 13. Report the actual number and name any where you
   disagree with my read.
5. Locals with `embedded_date_conflict` true.
6. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Re-extraction. The confusion matrix from task 4 is what will decide that, later.
- Displaying wage data. Still candidates only.
- Hosting, domain, email backend, trademark.
