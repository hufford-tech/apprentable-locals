# Task: Davis-Bacon, round 2 — scoped pull, parser, join, display

Working dir is `C:\Users\andre\ibew`. Continues `PROMPT_davisbacon_round1.md`, whose
task 1 is complete. Read that file's constraints section; they all still apply.

## What round 1 established

- Official source is SAM.gov's public wage determination pages.
  URL pattern: `https://sam.gov/wage-determination/{WD_NUMBER}/{MODIFICATION}`
- **No API, no bulk endpoint, no inventory endpoint.** Individual public pages only.
- Base wage and fringe are reliably separate columns.
- **Fringe is not always a fixed dollar amount.** Observed forms include `14.91`,
  `27.43%+12.16`, and `3%+24.18`. A percentage component is a percentage *of the base
  rate*.
- The determination header carries an effective/publication date. The classification
  identifier carries its own CBA or survey date. **These are different dates and must
  not be conflated.**
- Confirmed the core premise: `OH20260074/1`, Building, Cuyahoga County, contains
  `ELEC0038-005`, Electrician, base `$33.05`, fringe `$14.91`. `ELEC0038` is IBEW
  Local 38 Cleveland.
- A national pull cannot be counted from the public interface and would exceed 500
  requests.

## The scoping decision

Your recommendation was a narrower pull. Here is the shape it should take, and the
reasoning, because it changes the arithmetic in our favour.

**A single determination lists many classifications.** A state building determination
covering several counties will name multiple `ELEC` codes for different locals in one
document. So do not think of this as one fetch per local. Fetch a document, then
**harvest every `ELEC` code in it**, not only the one you were looking for. The yield
per request is potentially several locals.

**Prioritise by population, and stop when the marginal yield collapses.**

- Order the 244 locals by `population_current_served_inside` descending.
- Work state by state, starting with the states containing the most top-100 locals.
- After each state, record cumulative coverage: how many of the 244 now have a union
  `ELEC` rate, and how many new locals that state's documents added.
- **Hard cap: 400 requests total.** Stop at the cap regardless of coverage.
- **Early stop:** if three consecutive states each add fewer than 2 new locals, stop and
  report. The tail is not worth the requests.

Discovering WD numbers without an inventory endpoint: determine whether SAM.gov's search
accepts URL parameters you can request directly (state, county, construction type). If
it does, use it. If it does not, WD numbers follow `{STATE}{YEAR}{SEQUENCE}`, e.g.
`OH20260074`, so bounded sequential probing within a state is viable — but count every
probe against the 400 cap and stop probing a state once you have covered its counties.
Report which method you used.

Cache every fetched page to `raw/davisbacon/` on first fetch. A second parse run must
make zero network requests, and you will prove that in task 6.

## Task 1: the parser

Write `parse_davisbacon.py`. Per determination, per classification, emit to
`out/davisbacon_rates.csv`:

`wd_number`, `wd_modification`, `wd_effective_date`, `state`, `counties`,
`construction_type`, `classification_code`, `classification_text`,
`cba_or_survey_date`, `base_rate`, `fringe_raw`, `fringe_fixed`, `fringe_pct`,
`fringe_computed`, `total_rate`, `is_union_rate`, `local_number_from_code`

Rules:

- **Fringe parsing is the part most likely to go wrong.** Store `fringe_raw` verbatim,
  always. Then decompose:
  - `14.91` → `fringe_fixed = 14.91`, `fringe_pct = 0`
  - `27.43%+12.16` → `fringe_pct = 27.43`, `fringe_fixed = 12.16`
  - `3%+24.18` → `fringe_pct = 3`, `fringe_fixed = 24.18`
  - `fringe_computed = base_rate × (fringe_pct/100) + fringe_fixed`
  - `total_rate = base_rate + fringe_computed`
  If you encounter a form you cannot decompose, set the numeric fields empty, keep
  `fringe_raw`, and flag the row. Never guess at a format you have not seen.
- `is_union_rate` true only when the code is a union identifier such as `ELEC0038-005`.
  Survey rates use a different prefix, typically `SU` plus state and year. **A survey
  rate is a weighted average of union and non-union work and is not IBEW scale.**
  Classify, never blend.
- `local_number_from_code`: `ELEC0038-005` → `38`. Strip leading zeros, handle the
  `-NNN` suffix, and be careful with codes that are not four digits.
- Keep `wd_effective_date` and `cba_or_survey_date` in separate columns. Round 1 flagged
  the conflation risk explicitly.
- Parse all construction types. Retain them all in the CSV. Only `building` reaches the
  display path, because residential rates are far lower and must never be shown as
  commercial inside wireman scale.

Unit-test the fringe decomposer against all three observed forms plus a malformed input,
in a new `test_davisbacon.py`.

## Task 2: scoped pull

Run the pull per the scoping section. Report:

- method used to discover WD numbers
- requests made, pages cached, failures with reasons
- **the coverage curve**: after each state, cumulative locals covered and new locals
  added by that state
- whether you hit the 400 cap, the early-stop rule, or ran out of useful states

## Task 3: join to the 244 locals

Two independent paths, then reconcile.

1. **By local number** from `local_number_from_code`. Strongest, the code names the local.
2. **By county**, via `out/jurisdictions.csv` inside rows and `census_fips`.

Emit `out/local_wage_davisbacon.csv`: `local_union_id`, `lu_number`, `charter_city`,
`population`, `journeyman_base_low`, `journeyman_base_high`, `fringe_low`, `fringe_high`,
`total_low`, `total_high`, `wd_effective_date_newest`, `wd_effective_date_oldest`,
`county_match_count`, `join_method` (`local_code`, `county`, `both`), `is_union_rate`,
`wd_numbers`, `confidence`, `flags`.

- Ranges, never averages, and **strictly within one field**. A base range holds only base
  rates. The scraping round failed precisely because a range spanned base and total.
- Where both join paths yield a figure and they differ by more than 10%, flag it, prefer
  `local_code`, and report every case.
- Survey-only locals get `confidence = low` and are excluded from display.

## Task 4: compose apprentice pay

`out/wage_reconciled.csv` holds `apprentice_start_pct` and `apprentice_top_pct` from the
scraping round, derived from statements like LU 20's "begins at 50% of the Journeyman
hourly rate and progresses to 80%". That was the cleanest signal in that whole round.

`apprentice_start_hourly = journeyman_base × apprentice_start_pct`, only where both
exist and the base is a union rate. Set `apprentice_pay_is_derived = true` and carry both
inputs so the arithmetic is auditable on the page.

Where the scraping round also found a scraped apprentice hourly figure, compare. Within
15% is mutual validation. Report every case either way.

## Task 5: validate

Test set, with the scraped figures:

```
LU  38  Cleveland           expect base ~33.05, fringe ~14.91   <-- round 1 ground truth
LU  20  Dallas-Fort Worth   scraped base 40.65, apprentice 20.33 @ 50%
LU 129  Lorain              scraped base 41.49, "Total Journeyman Wireman $65.66"
LU 369  Louisville          scraped base 37.88, apprentice 17.69 @ 50%
LU 234  Castroville         scraped base range 65.16-84.49, quote showed $70.41
LU 481  Indianapolis        scraped package 57.43-78.71
LU 602  Amarillo            scraped base 26.07-49.10
LU 890  Janesville          scraped package 40.70
LU 302  Martinez            scraped base 26.50-27.30   <-- believed WRONG, real ~2x
```

Two questions I want answered:

- Does LU 38 Cleveland come out at $33.05 base and $14.91 fringe? That is a direct
  round 1 observation and the parser must reproduce it exactly. If it does not, the
  parser is wrong.
- Does LU 302 Martinez land around $60 to $70? If it does, that independently confirms
  both that the scrape was broken and that this source is sound. It is the most
  informative single number in this round.

Plausibility backstop, flag rather than drop, and report: union inside wireman base $22
to $95, total package $30 to $150 for 2026.

## Task 6: display and verify

Display rules are unchanged from `PROMPT_davisbacon_round1.md` task 7. Re-read them.
Summary: base and fringe as separate lines plus total, apprentice pay labelled derived
with its inputs visible, effective date always, source cited with a link to the
determination, one line noting Davis-Bacon is the prevailing wage on federally funded
work. Locals without a union rate show no section at all, not a blank row.

**No wage figures in JSON-LD.**

Verify:

1. Rebuild `out/frontend_data.json`, both finder builds, all 244 static pages.
2. ZIP mismatches zero. These 12 resolve: 02138, 10001, 60601, 94110, 75201, 33101,
   98101, 80202, 19104, 89101, 43201, 37201.
3. 244 unique slugs, zero dangling links.
4. `SHOW_CONFIDENCE`, `STATUS_DISPLAY`, `WAGE_DISPLAY` all strip cleanly.
5. Zero external asset requests in either build. The map is inline SVG, keep it that way.
6. No wage figures in any JSON-LD block.
7. 100 `compute_status.py` tests pass, 22 node tests pass, both untouched.
8. **Second parse run makes zero network requests.** Prove it.
9. List every file you modified.

## Report

1. WD discovery method, requests made, and the coverage curve by state.
2. **How many of the 244 have a union-rate journeyman base.** The headline.
3. Survey-only count, and no-match count.
4. LU 38 Cleveland: parsed base and fringe versus the round 1 observation.
5. LU 302 Martinez: the figure, and whether it confirms the scrape was wrong.
6. The full task 5 comparison table.
7. Local-code versus county join disagreements over 10%.
8. Derived apprentice pay count, and agreement rate against scraped figures.
9. Oldest and newest `wd_effective_date` in the matched set.
10. Any fringe format you could not decompose.
11. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- `compute_status.py`, `statement_evidence.py`, `window_rules.py`.
- Re-scraping union websites for wages. Closed.
- Any git command. Leave work in the tree, print files touched, Andrew commits.
- Hosting, domain, email backend, trademark.
