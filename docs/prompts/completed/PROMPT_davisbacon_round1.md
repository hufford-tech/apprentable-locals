# Task: journeyman and apprentice pay from Davis-Bacon wage determinations

Working dir is `C:\Users\andre\ibew`. This round replaces the failed wage-scraping
approach with a federal source.

## Run this AFTER `PROMPT_codex_round2.md` finishes

Both rounds own the build scripts and the wage display path. Do not run them
concurrently. If `PROMPT_codex_round2.md` has not completed, stop and say so.

Round 7 is committed. `compute_status.py` has 100 passing tests, `TODAY = 2026-08-10`.
Do not modify `compute_status.py`, `statement_evidence.py`, or `window_rules.py` at all
this round. You do not need them.

## Why this round exists

The wage-scraping round produced 8 usable locals out of 244, and four of those eight
conflated journeyman base pay with total package. LU 129 Lorain showed $65.66 inside its
base range when its own source text calls that figure "Total". LU 302 Martinez showed a
journeyman base of $26.50 in Contra Costa County, where the real figure is roughly
double, because an apprentice starting range populated the journeyman field.

The figures mostly are not on the pages we crawled. But DOL publishes them.

**Davis-Bacon wage determinations** give prevailing wage rates by county for every
state, and in heavily unionized markets they are derived directly from IBEW collective
bargaining agreements. The properties that matter here:

- The classification code embeds the local number. `ELEC0134` is IBEW Local 134. That
  joins to our primary dataset directly, not merely by county.
- **Base rate and fringe rate are listed as separate fields.** That is precisely the
  distinction that broke the scraping round.
- Each determination carries an effective date, so freshness is published rather than
  inferred.
- Rates are broken out by construction type: building, residential, highway, heavy. We
  want **building**. Inside wireman commercial work is building construction.

Reference material, read before writing code:
- https://www.dol.gov/agencies/whd/government-contracts/prevailing-wage-resource-book/db-wage-determinations
- https://www.dol.gov/agencies/whd/government-contracts/construction/faq
- an example determination: https://sam.gov/wage-determination/LA20260026/0

## CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction of local websites.** Never
  write `out/extraction_v2.csv`.
- **Do not run any `pass*.py` script.**
- **Network is permitted this round**, unlike every previous round, but only against
  `dol.gov`, `sam.gov`, and any official DOL or SAM endpoint you identify in task 1.
  Nowhere else. No scraping of union websites.
- **Cache every fetched document to `raw/davisbacon/`** on first fetch and read from
  cache afterward. Re-parsing must never require re-fetching. This is the pattern that
  kept the original crawl affordable.
- Be polite: sequential requests, 1 second apart, a real User-Agent, retry twice with
  backoff, and stop if you see rate limiting or a 403 pattern.
- **Do not run any git command.** Leave work in the working tree and print, per task,
  what changed and which files you touched. Andrew commits.
- Andrew is not available. Log blockers to `out/davisbacon_blockers.csv` and continue.
- 100 `compute_status.py` tests and 22 node tests must still pass at the end.

---

## Task 1: establish the access path, then STOP and report

**Do not mass-fetch anything until this task is reported.** I do not know the best
access route and I would rather you determine it than guess.

Investigate, in rough order of preference:

1. A bulk or programmatic download of current Davis-Bacon determinations. Check whether
   SAM.gov exposes a wage-determination API, what authentication it needs, and whether
   a free API key is required. If a key is required and you do not have one, note it as
   a blocker and fall back.
2. Per-state general determination documents. One determination typically covers many
   counties and lists every classification, which would mean tens of documents rather
   than thousands.
3. Individual determination pages at `sam.gov/wage-determination/{number}/{rev}`.

Then **pilot three states only**: Ohio, Texas, California. Chosen because we have
high-population locals in each with scraped figures to check against, and because they
differ in how unionized the electrical trade is.

Report before continuing:

- which access path works, and the exact URL pattern
- how many documents a full national pull would require
- a sample of the raw text around an `ELEC` classification, so I can see the format
- whether base and fringe are reliably separate fields
- whether the effective date is reliably present

If a full national pull would need more than roughly 500 requests, say so and propose a
narrower scope before proceeding.

## Task 2: the parser

Write `parse_davisbacon.py`. Extract, per determination, per classification:

`wd_number`, `wd_revision`, `effective_date`, `state`, `county_fips` (or county name if
FIPS is not published, and map it), `construction_type`,
`classification_code`, `classification_text`, `base_rate`, `fringe_rate`,
`total_rate`, `is_union_rate`, `local_number_from_code`.

Rules:

- `is_union_rate` is true when the classification code is a union identifier, e.g.
  `ELEC0134`. Survey-derived rates use a different prefix, typically `SU` followed by a
  state and year, e.g. `SUOH2011-xxx`. **A survey rate is a weighted average of union
  and non-union work and is not IBEW scale.** Classify it, never silently mix it in.
- `local_number_from_code`: parse the digits out of `ELEC0134` to `134`. Strip leading
  zeros. Be careful, some codes carry suffixes.
- `total_rate` should be `base_rate + fringe_rate`. Compute it and also capture any
  published total; if they disagree by more than a cent, flag it.
- Keep only `construction_type == building` for the display path, but parse and retain
  all types in the CSV. Residential rates are much lower and must never be confused
  with commercial inside wireman scale.

Emit `out/davisbacon_rates.csv`, one row per determination-classification-county.

## Task 3: national pull

Once task 1's approach is approved by the numbers, fetch the rest. Cache everything.
Report: documents fetched, documents already cached, failures with reasons, and total
rows parsed.

## Task 4: join to the 244 locals

Two independent join paths. Do both, then reconcile.

1. **By local number**, from `local_number_from_code`. Strongest, because the code names
   the local directly.
2. **By county**, using `out/jurisdictions.csv` inside-jurisdiction rows and
   `census_fips`. A local covering many counties will match several determinations.

Emit `out/local_wage_davisbacon.csv`: `local_union_id`, `lu_number`, `charter_city`,
`population`, `journeyman_base_low`, `journeyman_base_high`, `fringe_low`, `fringe_high`,
`total_low`, `total_high`, `effective_date_newest`, `effective_date_oldest`,
`county_match_count`, `join_method` (`local_code`, `county`, `both`),
`is_union_rate`, `wd_numbers`, `confidence`, `flags`.

Rules:

- Where both join paths produce a figure and they **disagree by more than 10%**, flag it
  and prefer the `local_code` match. Report every disagreement.
- Ranges again, never averages, and this time **strictly within one field**. Base range
  holds only base rates. The scraping round failed precisely because a range spanned
  base and total.
- A local matching only survey rates (`is_union_rate` false) gets `confidence = low` and
  is excluded from display. Say how many that is.
- Report coverage: how many of the 244 got a union-rate journeyman base. **My
  expectation is well over 150.** If it comes back under 100, something is wrong with
  the join and I want to know before you build anything on it.

## Task 5: compose apprentice pay

`out/wage_reconciled.csv` from the previous round holds `apprentice_start_pct` and
`apprentice_top_pct`, derived from statements like LU 20's "begins at 50% of the
Journeyman hourly rate and progresses to 80%". That was the cleanest signal in the whole
scrape, 196 candidates.

Compose: `apprentice_start_hourly = journeyman_base × apprentice_start_pct`.

- Only where both inputs exist and the journeyman base is a union rate.
- Present it as **derived**, never as a published figure. Add
  `apprentice_pay_is_derived = true` and carry both inputs so the arithmetic is
  auditable on the page.
- Where the previous round also found a *scraped* apprentice hourly figure, compare it
  to the derived one. Agreement within 15% is a strong validation signal for both.
  Report every case, agreeing or not.

## Task 6: validate against the scraped figures, and against reality

The previous round's 8 display-tier locals are your test set. Known scraped values:

```
LU  20  Dallas-Fort Worth   base 40.65            apprentice 20.33 @ 50%
LU 234  Castroville         base 65.16-84.49      quote showed Journeyman $70.41
LU 129  Lorain              base 41.49            "Total Journeyman Wireman $65.66"
LU 369  Louisville          base 37.88            apprentice 17.69 @ 50%
LU 481  Indianapolis        package 57.43-78.71
LU 602  Amarillo            base 26.07-49.10
LU 302  Martinez            base 26.50-27.30      <-- known WRONG, real figure ~2x
LU 890  Janesville          package 40.70
```

For each, report the Davis-Bacon figure beside the scraped one. Two things I want to
learn:

- Does Davis-Bacon corroborate LU 20, LU 129's $41.49 base, and LU 369?
- Does Davis-Bacon show LU 302 Martinez around $60 to $70, confirming the scrape was
  wrong? If it does, that is strong evidence the new source is sound.

Also apply a plausibility band as a backstop: union inside wireman base $22 to $95,
total package $30 to $150 for 2026. Anything outside gets flagged, not dropped, and
reported. These bands are a sanity check, not a source of truth.

## Task 7: display

Re-enable `WAGE_DISPLAY` for this path only. `wage_rules.py` and the old scraped display
stay switched off; do not delete them.

For a local with a union-rate Davis-Bacon figure, show:

- **Journeyman scale**, base and fringe as separate lines, plus total. Never one blended
  number.
- **Apprentice starting pay**, where derived, labelled as derived, with the percentage
  and the journeyman base it was computed from visible.
- The **effective date**, always.
- The source, stated plainly: "U.S. Department of Labor Davis-Bacon prevailing wage
  determination [WD number], effective [date]", linking to the determination.
- One line of honest framing: Davis-Bacon is the prevailing wage on federally funded
  construction, and where the rate is a union rate it reflects the local IBEW
  agreement. Contractors on private work may pay differently.

For locals with only survey rates or no match, omit the section entirely. Not a blank
row, not "unknown". Omit it.

**Wage figures still must not appear in JSON-LD.** Structured data gets indexed as
authoritative and cannot be retracted.

## Task 8: verify

1. Rebuild `out/frontend_data.json`, both finder builds, all 244 static pages.
2. ZIP mismatches zero. These 12 still resolve: 02138, 10001, 60601, 94110, 75201,
   33101, 98101, 80202, 19104, 89101, 43201, 37201.
3. 244 unique slugs, zero dangling links.
4. All flags strip cleanly: `SHOW_CONFIDENCE`, `STATUS_DISPLAY`, `WAGE_DISPLAY`.
5. **Zero external asset requests** in either build. The map is inline SVG and must
   stay that way.
6. No wage figures in any JSON-LD block.
7. 100 `compute_status.py` tests pass, 22 node tests pass, both untouched.
8. Every fetched determination is cached under `raw/davisbacon/` and a second parse run
   makes zero network requests. Prove it.
9. List every file you modified.

## Report

Per task: what changed, the proving count, files touched. Then:

1. Access path and total documents fetched.
2. **Coverage: how many of the 244 have a union-rate journeyman base.** The headline
   number for this round.
3. How many have only survey rates, and how many no match at all.
4. The task 6 comparison table, scraped versus Davis-Bacon, all 8 locals.
5. Every case where the local-code join and the county join disagreed by more than 10%.
6. Derived apprentice pay: how many locals, and the agreement rate against scraped
   apprentice figures where both exist.
7. Oldest and newest effective dates across the matched set.
8. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- `compute_status.py`, `statement_evidence.py`, `window_rules.py`.
- Re-scraping union websites for wages. That approach is closed.
- Any git command.
- Hosting, domain, email capture backend, trademark.
