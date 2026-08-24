# Claude Code task: make the change monitor trustworthy

Working dir is `C:\Users\andre\ibew`.

## Concurrency

Codex may be running `PROMPT_davisbacon_round3.md`. It owns `pull_davisbacon.py`,
`parse_davisbacon.py`, `build_local_wage_davisbacon.py`, `test_davisbacon.py`,
`out/davisbacon_*`, `raw/davisbacon/`, all build scripts, all page templates, and all
build output.

You own: `monitor.py`, `run_monitor.bat`, `MONITOR_SETUP.md`, `out/monitor_*`, and any
new test file for the above.

Do **not** touch build scripts, page templates, build output, `compute_status.py`,
`statement_evidence.py`, `window_rules.py`, or anything Davis-Bacon.

**Do not rebuild anything.** You own git in this tree; Codex has been told not to touch
it. Prefix commits with `monitor:`.

Network is permitted, but only plain `requests` GETs against URLs already in
`out/monitor_state.json`. Do not fetch `sam.gov` or `dol.gov`; Codex is working those.

## The problem

The monitor ran twice: baseline at `2026-08-11T19:59Z`, second sweep at
`2026-08-13T01:34Z`. About 26 hours apart.

**99 of 219 URLs reported a changed hash. That is 45%.**

IBEW JATC websites do not rewrite 45% of their content in a day. The hash is catching
dynamic content: timestamps, session and CSRF tokens, cache-busting query strings on
assets, rotating banners, visitor counters, ad slots, "last updated" stamps that render
from the clock rather than from the content.

This matters more than it looks. `is_stale` is empty everywhere by design, and
`days_since_evidence` has no floor, because both were going to be derived from
`last_changed` once history accumulated. At a 45% daily false-positive rate the monitor
flags everything, which is the same as flagging nothing. It also means the Firecrawl
trigger, if it were wired up, would fire on 99 locals a day against a 10,000-credit
annual budget.

**Do not schedule this until the false-positive rate is measured and reduced.**

---

## Task 1: measure the noise floor

The cheapest possible diagnostic: **run the sweep twice, ten minutes apart.** Anything
whose hash differs across two runs that close together is, by definition, noise. No union
hall edits its apprenticeship page twice in ten minutes.

Write `out/monitor_noise_audit.csv`: `local_union_id`, `lu_number`, `url`, `hash_run_a`,
`hash_run_b`, `differs`, `bytes_run_a`, `bytes_run_b`, `first_diff_offset`,
`diff_sample_a` (200 chars around the first difference), `diff_sample_b` (200 chars).

That `diff_sample` pair is the whole point. It shows you exactly what is churning, and it
is what you will build the normaliser from in task 2.

Report:

- the false-positive rate: how many of 219 differ over ten minutes
- a categorised breakdown of what is changing, derived from the diff samples. I expect
  timestamps, tokens, counters and cache-busting parameters, but let the data say.
- how much overlap there is between these unstable URLs and the 99 flagged in the
  26-hour comparison. If most of the 99 are also unstable at ten minutes, then almost
  none of those 99 were real changes.

**Stop and report after this task before changing the hash.** I want to see the noise
categories before you write rules against them.

## Task 2: normalise harder

Build the normaliser from what task 1 actually found, not from my guesses. Candidates,
in rough order of likely impact:

- strip `<script>`, `<style>`, `<noscript>`, HTML comments, and `<meta>` (already partly
  done, verify)
- redact anything date-shaped or time-shaped: ISO dates, `M/D/YYYY`, `Month D, YYYY`,
  `HH:MM`, day names, and bare 4-digit years **only when adjacent to a date word**, since
  a bare year may be real content like "2026 Program"
- strip query strings from asset URLs (`?v=`, `?ver=`, `?cb=`, numeric cache busters)
- redact long hex or base64 runs, which are tokens, nonces and CSRF values
- redact standalone numbers over 4 digits, which are counters and IDs
- collapse whitespace, lowercase, then hash

Then consider a stronger move: **hash only the visible text of the main content region**
rather than the whole document. Nav, footer, sidebars and ad slots are where most churn
lives, and none of them carry application status. If you can identify a main content
region reliably across these sites, do it and report the coverage; if you cannot, say so
and stay with whole-document text.

Keep the old hash alongside the new one in state as `last_hash_legacy`, so we can compare
behaviour rather than losing the baseline.

## Task 3: require corroboration before declaring a change

Even with a good normaliser, a single differing sweep is weak evidence. Add a
confirmation step:

- a change is *candidate* on the first differing sweep
- it becomes *confirmed* only when the next sweep produces the same new hash
- only a confirmed change updates `last_changed` and writes to
  `out/monitor_changes.csv`
- a candidate that reverts on the next sweep is logged to
  `out/monitor_flapping.csv` with a count, because a URL that flaps repeatedly is
  telling you its normaliser rule is still wrong

Add `pending_hash` and `pending_since` to the state records.

## Task 4: re-baseline and prove it

1. Re-baseline all 219 URLs with the new normaliser.
2. Run the ten-minute double-sweep again. **Report the new false-positive rate.**
3. My bar: **under 5%.** If you cannot get there, do not claim success. Report where it
   landed, which URLs remain unstable, and what is still churning in them. A known 12%
   with a named list of offenders is far more useful to me than an unexplained 5%.
4. Update `MONITOR_SETUP.md`: keep the Task Scheduler instructions, and add a short
   plain-language section on what a confirmed change means, what the false-positive rate
   currently is, and why the schedule should be daily rather than hourly.
5. Emit `out/monitor_freshness.csv` as before, with `monitor_days_since_change` now based
   on confirmed changes only.

## Task 5: verify

1. `python monitor.py --limit 3` still works and makes exactly 3 requests.
2. `--dry-run` makes zero requests.
3. State file remains keyed by `local_union_id`.
4. Unit tests for the normaliser: feed it two documents differing only in a timestamp, a
   session token, a cache-busting query string, and a counter, and assert the hashes
   match. Then feed it two documents differing in a real sentence about applications and
   assert they differ. That second test is the one that matters — an over-aggressive
   normaliser that hashes everything to the same value would score a perfect
   false-positive rate and be completely useless.
5. Confirm you touched nothing outside your ownership list and did not rebuild.
6. List every file you modified.

## Report

1. **Task 1 noise floor: false-positive rate over ten minutes, and the categories of
   churn with examples.** Lead with this.
2. Overlap between the unstable set and the 99 flagged at 26 hours. State plainly how
   many of those 99 you now believe were real.
3. The normaliser rules you implemented and why, tied to the evidence.
4. **New false-positive rate after re-baselining, against the 5% bar.**
5. Remaining unstable URLs with what is still churning in them.
6. Whether you could isolate a main content region, and for how many of the 219.
7. Your recommendation: is this ready to schedule daily, yes or no.
8. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Feeding freshness into `compute_status`. Not until this is trustworthy and a few weeks
  of confirmed history exist.
- Firecrawl. Not one call. When a confirmed change fires, log it; Andrew reviews.
- Anything Davis-Bacon, any build script, any page template.
- Hosting, domain, email backend, trademark.
