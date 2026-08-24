# Task: Davis-Bacon round 3 — validate first, then filter classifications

Working dir is `C:\Users\andre\ibew`. Continues `PROMPT_davisbacon_round2.md`.

**The 54 wage sections currently rendering on the site are unvalidated and contain
wrong-trade rates. Treat them as broken until task 2 proves otherwise.**

## Concurrency

A separate Claude agent may be running `PROMPT_monitor_round1.md`. It owns `monitor.py`,
`out/monitor_*`, `run_monitor.bat`, `MONITOR_SETUP.md`. Do not touch those.

You own: `pull_davisbacon.py`, `parse_davisbacon.py`,
`build_local_wage_davisbacon.py`, `test_davisbacon.py`, `out/davisbacon_*`,
`out/local_wage_davisbacon.csv`, `raw/davisbacon/`, `build_frontend_data.py`,
`build_local_pages.py`, `page_template.html`, and all build output.

Do **not** touch `compute_status.py`, `statement_evidence.py`, `window_rules.py`.

**No git commands.** Leave work in the tree, print files touched per task, Andrew commits.

## What round 2 got right, and what it got wrong

Right: the access path (`https://sam.gov/api/prod/wdol/v1/wd/{WD}/{REV}`), the fringe
decomposer (all formats decomposed, none unknown), the caching (401 documents, second
parse made zero requests), and the premise. Boston $66.17, Chicago $57.75, Philadelphia
$63.97, Pittsburgh $49.11 and St. Louis $49.29 all look correct for 2026 inside wireman.
**The source is sound.**

Wrong, and both are serious:

### 1. Nothing was validated

All ten validation targets came back `NO MATCH`: LU 38, 20, 129, 369, 234, 481, 602,
302, 890, 613. The 400-request cap was exhausted before reaching `OH20260074/1`, which
round 1 had already identified **by URL** as containing `ELEC0038-005` at base $33.05,
fringe $14.91. The one document we already knew about was never fetched.

### 2. `ELEC` codes cover many trades, and the join mixed them

Raw rows from the current cache:

```
LU 134 Chicago    $57.75  ELECTRICIAN                                    <-- inside wireman
                  $51.14  MAINTENANCE, REPAIR AND SERVICE OF RADIO, TELEVISION...
LU   3 New York   $62.00  ELECTRICIAN                                    <-- inside wireman
                  $32.00  ELECTRICIAN (JOBBING, AND MAINTENANCE AND REPAIR WORK)
LU  34 Peoria     $45.65  ELECTRICIAN (PEORIA DIVISION - ...)             <-- inside wireman
                  $26.58  ELECTRICIAN (RESIDENTIAL)
LU 569 San Diego  $58.95  ELECTRICIAN: (ALL OTHER WORK, INCLUDING 4 STORIES RESIDENTIAL)
                  $33.10  TRAFFIC SIGNAL, STREET LIGHT AND UNDERGROUND WORK
                  $67.16  ELECTRICIAN: (TUNNEL WORK) CABLE SPLICER
```

So the displayed range for Chicago is $51.14 to $57.75 when the real inside wireman base
is $57.75, and Peoria shows a $26.58 low that is a residential rate.

And the most frequent `ELEC` classifications across the whole pull are **LINE
CONSTRUCTION**: lineman, groundman, cable splicer, flagman, substation, overhead and
underground. That is outside construction, a different trade with a different
apprenticeship. This dataset is class-i inside wireman only. It is the same lineman
contamination that the competitor cross-check found on LU 1426.

---

## Task 1: classification filter

Add `classify_electrical_work(classification_text) -> 'inside_wireman' | 'excluded'`
plus an `exclusion_reason`, in `parse_davisbacon.py`. Named module-level constants, not
inline regexes.

**Exclude** when the text indicates any of:

- line construction: `LINE CONSTRUCTION`, `LINEMAN`, `GROUNDMAN`, `FLAGMAN`,
  `SUBSTATION`, `SWITCHING`, `OVERHEAD AND UNDERGROUND`, `POLE`
- residential as the primary scope
- low voltage / communications: `LOW VOLTAGE`, `TELEDATA`, `SOUND`, `COMMUNICATION`,
  `CATV`, `TELEVISION`, `RADIO`, `FIBEROPTIC`, `MASTER TELEVISION DISTRIBUTION`
- street work: `TRAFFIC SIGNAL`, `STREET LIGHT`, `UTILITY`
- `TUNNEL`
- service tiers: `JOBBING`, `MAINTENANCE AND REPAIR`, `SERVICE OF`

**Two traps that will produce wrong numbers if you get them backwards:**

1. `ELECTRICIAN: (ALL OTHER WORK, INCLUDING 4 STORIES RESIDENTIAL...)` **is** the inside
   wireman rate for LU 569. A naive `RESIDENTIAL` blacklist would delete San Diego's
   correct figure. Exclude only when residential is the *primary scope*, as in
   `ELECTRICIAN (RESIDENTIAL)` or `ELECTRICIAN (RESIDENTIAL, 1-3 STORIES)`. Keep it when
   the text says *including* residential.
2. `CABLE SPLICER` appears both under line construction and as a higher-rated **inside**
   classification, e.g. `ELECTRICIANS (ELECTRICAL CONTRACTS OF $500,000 AND OVER): CABLE
   SPLICER`. Neither is the journeyman wireman rate we want. Exclude both, but record the
   distinction in `exclusion_reason` so it is visible.

**Change how multiple survivors are handled.** Round 2 emitted a range across them, which
is what hid the contamination. New rule:

- If exactly one classification survives, that is the figure.
- If several survive and differ only by **geography** — the same classification scoped to
  different counties or divisions of the local's jurisdiction, as in LU 34's Peoria and
  Galesburg divisions — a range is legitimate. Emit it and set
  `range_basis = 'geographic'`.
- If several survive and differ by **qualifier** — contract size tiers, work type — do
  **not** range. Take the least-qualified plain `ELECTRICIAN` classification as the
  journeyman wireman rate, set `range_basis = 'single_classification'`, and list the
  alternatives in a new `alternate_classifications` column.
- Flag and report any local where a surviving base range still exceeds 1.4x.

Also fix the HTML entity double-escaping: `LINEMAN &amp;amp; TE` should be `LINEMAN & TE`.

## Task 2: re-derive from the existing cache, then validate. No new requests.

You already have 401 cached documents. **Re-run the parse and join with the new filter
before fetching anything.** This is free and it immediately tells us whether the filter
works.

Report, from cache only:

- how many of the 54 change, and to what
- Chicago should become a single $57.75, not a range
- Peoria should become $45.65, losing the residential $26.58
- New York should become $62.00, losing the jobbing $32.00
- San Diego should keep roughly $58.95 to $59.70 and lose the traffic signal and tunnel rows
- how many locals now have zero surviving inside-wireman classifications, so coverage drops
- how many locals still exceed a 1.4x base range, with their classifications

## Task 3: fetch the validation set. Bounded, at most 60 requests.

**Do this before any further coverage pull.** Fetch, targeted, in this order:

1. `OH20260074/1` directly. It is a known URL and must yield `ELEC0038-005` at base
   $33.05, fringe $14.91. **If your parser does not reproduce those two numbers exactly,
   the parser is wrong and everything downstream is void. Stop and report.**
2. Determinations covering the counties of: LU 302 Martinez CA, LU 20 Dallas-Fort Worth
   TX, LU 129 Lorain OH, LU 369 Louisville KY, LU 234 Castroville CA, LU 613 Atlanta GA,
   LU 98 Philadelphia PA, LU 481 Indianapolis IN, LU 602 Amarillo TX, LU 890 Janesville
   WI.

Use the largest inside county from `out/jurisdictions.csv` for each. Cache everything.

Then report a comparison table: local, scraped figure from the earlier wage round,
Davis-Bacon inside-wireman base and fringe, and whether they agree within 15%.

**LU 302 Martinez is the falsification test.** The scrape said $26.50 to $27.30 base in
Contra Costa County. If Davis-Bacon says roughly $60 to $70, that independently proves
the scrape was broken and this source is sound. That single number is worth more than
the other nine combined.

## Task 4: resume the coverage pull

Round 2 spent 400 requests to cache 186 determinations, so roughly half went to
discovery probes that yielded nothing. Improve that before spending more.

- Report the actual hit rate of your discovery method and what you changed.
- New budget: **300 additional requests**, on top of tasks 2 and 3.
- Same harvest-everything approach: take every `ELEC` code from each document.
- Priority order by remaining uncovered locals weighted by population. Georgia and
  Tennessee added zero locals in round 2 and Atlanta at 7.9M is still uncovered, so
  investigate whether those states' determinations were even reachable.
- Early stop: three consecutive states each adding fewer than 2 new inside-wireman
  locals.
- Report the coverage curve again, and the count of locals with an inside-wireman base.

## Task 5: apprentice pay, display, verify

Recompose `apprentice_start_hourly = inside_wireman_base × apprentice_start_pct` from
`out/wage_reconciled.csv`. Derived only, labelled derived, both inputs visible.

Display rules unchanged from round 1 task 7 and round 2 task 6: base and fringe as
separate lines plus total, effective date always, source cited with a link, the line
about Davis-Bacon being prevailing wage on federally funded work. Add one clause to the
sourcing line naming the classification, e.g. "Electrician (inside wireman) classification
ELEC0134-001", because the whole failure of round 2 was classification ambiguity.

Locals with no surviving inside-wireman classification show no wage section. Not a blank
row.

Verify:

1. Rebuild bundle, both finder builds, 244 static pages.
2. ZIP mismatches zero. These 12 resolve: 02138, 10001, 60601, 94110, 75201, 33101,
   98101, 80202, 19104, 89101, 43201, 37201.
3. 244 unique slugs, zero dangling links.
4. `SHOW_CONFIDENCE`, `STATUS_DISPLAY`, `WAGE_DISPLAY` all strip cleanly.
5. Zero external asset requests. The map is inline SVG.
6. No wage figures in JSON-LD.
7. 103 `compute_status.py` tests pass, 22 node tests pass, both untouched.
8. Second parse run makes zero network requests. Prove it.
9. Unit tests for `classify_electrical_work` covering every exclusion category plus both
   traps in task 1.
10. List every file you modified.

## Report

1. **LU 38 Cleveland: parsed base and fringe versus $33.05 / $14.91.** Lead with this.
   If it does not match, nothing else in the report matters.
2. **LU 302 Martinez: the figure, and whether it confirms the scrape was wrong.**
3. The full comparison table for all ten validation locals.
4. Task 2 cache re-derive: what changed among the 54, and the four specific locals named.
5. Final coverage: locals with an inside-wireman base, survey-only, no match.
6. Locals still exceeding a 1.4x base range, with classifications.
7. Discovery hit rate, before and after.
8. Whether Georgia and Tennessee determinations were reachable, and Atlanta's status.
9. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- `compute_status.py`, `statement_evidence.py`, `window_rules.py`, `monitor.py`.
- Re-scraping union websites for wages. Closed.
- Any git command.
- Hosting, domain, email backend, trademark.
