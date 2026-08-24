# Claude Code task: apprentice and journeyman pay, round 1

Working dir is this repo (`~/ibew`). Zero paid API cost, zero network, no
re-extraction. Deterministic Python over files already on disk.

Round 5 is committed. `compute_status.py` has 75 passing tests, `TODAY = 2026-08-10`.
`ibew_finder.html` and the 244 static pages both render `Apprentice pay` as
"Not yet collected" in two slots. This round fills them, or proves they should stay
empty for most locals.

## CONCURRENCY, read first

**This prompt runs at the same time as `PROMPT_status_round6.md` in a separate agent.**

You own, and may modify: `wage_rules.py` and `test_wage_rules.py` (both new),
`out/wage_*.csv`, `page_template.html`, the local page template, `site/local.css`,
`build_page.py`, `build_local_pages.py`, `build_frontend_data.py`, and **all build
output** (`ibew_finder.html`, `site/index.html`, `site/local/*.html`,
`out/frontend_data.json`, `site/data/*.json`).

You must **NOT** touch: `compute_status.py`, `statement_evidence.py`,
`window_rules.py`, or any `out/round6_*.csv`. The status agent owns those and is
changing them right now. If you need to know a local's status, read it from
`out/frontend_data.json` or call `compute_status` without editing it.

You own every build step, so run your rebuilds normally. Statuses may shift under you
while you work; that is expected and Andrew reruns the final build after both agents
finish.

**Do not run any git command. No `git add`, no `git commit`, no `git checkout`, no
`git stash`.** The other agent owns git in this working tree, and two agents committing
at once produces `.git/index.lock` failures that have already broken this repo once.
Leave your work uncommitted in the working tree; Andrew commits it himself once both
agents are done. Reading git is fine if you need it (`git show`, `git diff`), writing
is not.

Where this prompt says "one commit per task", instead finish each task, run its
verification, and print a one-line summary of what changed and which files you touched.
That printed list is what Andrew will use to write the commit.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction. No network.**
- **Do not run any `pass*.py` script.** **Never write `out/extraction_v2.csv`.**
- You may read `raw/` with targeted Python scans only. Extract matches, discard the
  page body. Never dump HTML into context.
- I am not available. Log blockers to `out/wage_blockers.csv` and continue.
- Full test suite green before you consider any task done. No git, see the
  concurrency section.
- **A wrong wage is worse than no wage.** Someone deciding whether to change careers
  will anchor on this number. Every rule below rejects rather than guesses, and the
  display bar is deliberately high. If a local ends up showing nothing, that is a
  correct outcome, not a failure.

## What already exists

`out/wage_candidates.csv` from the frontend round: 3,175 candidate rows across
190 of the 244 shown locals. Columns: `local_union_id`, `lu_number`, `source_file`,
`match_type`, `matched_text`, `parsed_value`, `confidence`.

Distribution: `explicit_rate` 2,070, `progression_table` 709, `pct_of_journeyman` 196,
`explicit_rate_total_package` 175, `explicit_rate_base_wage` 25.
Confidence: low 2,779, medium 396. 2,466 rows have a numeric `parsed_value`.

**Do not trust the hit rate.** I read the file. Findings you must design around:

### `explicit_rate` (65% of all rows) is mostly not wages

LU 1's top matches are hotel room prices from a training-event travel page:

> "**Bell Tower**](https://belltowerhotel.com/)<br>300 S Thayer St, 48104 | $221-$300
> call Reservations"

> "2455 Carpenter Rd, 48108 | $184-$214 / NTI2026"

A bare dollar figure near the word "rate" catches hotel rates, hall rental, dues,
initiation fees, donations, and ticket prices. Treat this match type as guilty until
proven otherwise.

### `progression_table` (709 rows) is navigation menus

`parsed_value` is empty on the ones I sampled and `matched_text` is a sidebar link
list: "[First Year](.../firstyear/) - [Second Year](...)". The regex found year labels
adjacent to each other and called it a table.

### `pct_of_journeyman` (196 rows) is the cleanest signal in the file

> LU 12: "Wages for this program start at 50% of Journeyman Scale"

> LU 20: "begins at 50% of the Journeyman hourly rate at the start of the first year
> and progresses to 80% of the Journeyman rate in the last year"

> LU 95: "pay for a first year Apprentice in Local 95 is $13.03 per hour, which is
> based on 50% of the Journeyman Wireman Scale"

Semantically unambiguous, and LU 95 gives you a percentage and an hourly figure in one
sentence, which is a free consistency check.

### `explicit_rate_total_package` (175) and `explicit_rate_base_wage` (25) hold the gold

> LU 60: "**Journeyman pay: $37.45/hr +fringes= $49.64/hr Total Package**"

> LU 82: "| 1st Year Apprentice | $18.12 | $5.92 | $24.04 | | 2nd Year Apprentice |
> $19.70 | ..."  (a real progression table with base, benefits, total)

> LU 129: "| Journeyman Wireman Base Pay | $51.04 | $46.63 | $41.49 | ..."
> (multi-column: several classifications or years on one row)

But also junk in the same bucket: LU 60's `$0.75` is a scheduled raise increment, not
a wage.

### The numbers are out of range

Across 2,466 numeric values: min 0.0, p10 1.15, median 28.29, p90 85.0, max 956.0.
**680 values (27.6%) are implausible as an hourly wage.**

---

## Task 1: `wage_rules.py`, plausibility and context gating

New module, importable and unit-testable. No I/O.

`classify_wage_candidate(row, page_context) -> {admissible, reject_reason, kind, value, basis}`

`kind` is one of `journeyman_base`, `journeyman_total_package`, `apprentice_hourly`,
`apprentice_pct`, `raise_increment`, `unknown`.

Reject rules, in order:

1. **Negative context.** Reject if the surrounding text contains hotel, motel, inn,
   room, reservation, nightly, per night, occupancy, rental, hall rent, dues,
   initiation, assessment, fee, fine, donation, raffle, ticket, dinner, golf,
   scholarship fund, per diem, mileage, parking. Name this `negative_context`. This
   alone should kill the LU 1 hotel rows.
2. **Source page irrelevance.** Reject if `source_file` clearly belongs to a
   non-wage page (events, travel, lodging, calendar, newsletter, obituary, minutes,
   bylaws, political action, retirees). Derive from the path and any page title you can
   cheaply recover. Name it `irrelevant_page`.
3. **Required positive context.** Admit only if the surrounding text contains a wage
   word (wage, pay, scale, rate of pay, per hour, hourly, /hr, compensation, earnings)
   **and** a trade word (journeyman, journeyworker, wireman, inside wireman,
   apprentice, JATC). Missing either → `insufficient_context`.
4. **Plausibility bounds**, applied by `kind`:
   - `journeyman_base`: $22 to $85 per hour
   - `journeyman_total_package`: $30 to $130 per hour
   - `apprentice_hourly`: $11 to $45 per hour
   - `apprentice_pct`: 30% to 90%
   Outside the band → `implausible_value`. Put the bands in named constants with a
   comment explaining they are 2026 US inside-wireman ranges and are a sanity filter,
   not a source of truth.
5. **Raise increments.** A value under $5 next to "additional", "increase", "effective"
   or "per hour, effective" is a scheduled raise, not a wage. Classify `kind` as
   `raise_increment` and exclude from display.

**Discard `progression_table` entirely** unless you can rewrite the detector to require
a year label adjacent to a plausible dollar amount **in the same table row**, the LU 82
shape. Link lists must not match. If you cannot make it precise, drop the match type
and say so. 709 rows of navigation menus are worth nothing.

## Task 2: effective dates

A wage with no date is a liability. A 2019 scale shown in 2026 is wrong, not stale.

Extend the scan to capture any effective date near an admitted wage: "effective
June 3, 2024", "as of 6/1/2025", "2025-2026 wage rates", a bare year in a table
caption. Emit `effective_date` and `effective_date_precision` (`day`, `month`, `year`,
`none`).

Anything with `effective_date` older than **36 months** before `TODAY`, or with
precision `none`, cannot reach the display tier in task 4. Undated wage figures are
the most dangerous thing in this dataset because they look authoritative.

## Task 3: `out/wage_reconciled.csv`, one row per local

Reduce the surviving candidates to a single record per local:

`local_union_id`, `lu_number`, `charter_city`, `population`,
`journeyman_base_low`, `journeyman_base_high`,
`journeyman_package_low`, `journeyman_package_high`,
`apprentice_start_hourly`, `apprentice_start_pct`, `apprentice_top_pct`,
`progression_json`, `effective_date`, `effective_date_precision`,
`candidate_count`, `admitted_count`, `evidence_quote` (300), `source_file`,
`consistency_check`, `tier`.

Rules:

- Where several admitted values share a `kind`, emit a **range**, not a mean. LU 129's
  multi-column row is several classifications, and averaging them invents a number
  nobody published.
- `consistency_check`: when both `apprentice_start_pct` and `apprentice_start_hourly`
  are present along with `journeyman_base_low`, verify
  `apprentice_hourly ≈ pct × journeyman_base` within 15%. Emit `pass`, `fail`, or
  `insufficient_data`. LU 95 is the worked example: $13.03 at 50% implies a journeyman
  scale near $26.06. A `fail` here means the figures came from different years or
  different programs, and must drop the local out of the display tier.
- `tier`:
  - `display` — at least one admitted value, `consistency_check` not `fail`,
    `effective_date` within 36 months with precision `day`, `month` or `year`, and at
    least two independent admitted candidates agreeing, or one from
    `explicit_rate_base_wage` / `pct_of_journeyman`
  - `review` — admitted values exist but fail the display bar
  - `reject` — nothing survived

## Task 4: display, only the `display` tier

In `page_template.html` and the local page template, replace the two
"Not yet collected" rows. Governed by a new config constant `WAGE_DISPLAY` that works
the same way `SHOW_CONFIDENCE` and `STATUS_DISPLAY` do: one line to switch off, with a
grep-verified build.

For a `display` local, show:

- Apprentice starting pay as published, as a range or a single figure with a `%` of
  journeyman scale where known
- Journeyman scale, base and total package labelled **separately**. Never conflate
  them. LU 60's $37.45 base and $49.64 package are both true and mean different things.
- The effective date, always, phrased plainly: "as published, effective June 2024"
- The verbatim source quote and a link to the page it came from
- One line of copy: pay is set by local collective bargaining agreements and changes;
  confirm with the local before relying on it

For `review` and `reject` locals, show nothing at all. Not "unknown", not a blank row.
Omit the section. A missing section reads as "we don't have this"; an empty labelled
row reads as "this local doesn't pay".

Do **not** put wage figures in the JSON-LD structured data on the static pages. Search
engines will surface them as authoritative and you will have no way to retract.

## Task 5: tests

New `test_wage_rules.py`, run with the existing suite. All 75 `compute_status` tests
must still pass, and `node --test test_finder_core.js` must stay at 22.

Fixtures from **real rows** in `out/wage_candidates.csv`:

- LU 1 hotel rows ($184, $214, $221, $300) → rejected `negative_context`
- LU 1 progression rows → rejected, navigation menu
- LU 12 "start at 50% of Journeyman Scale" → admitted, `apprentice_pct` 50
- LU 20 "begins at 50%... progresses to 80%" → admitted, start 50, top 80
- LU 95 "$13.03 per hour, which is based on 50%" → admitted, both fields,
  `consistency_check` derivable
- LU 60 "$37.45/hr +fringes= $49.64/hr Total Package" → two values, correctly split
  into base and package
- LU 60 "$0.75 per hour, effective June 3, 2024" → `raise_increment`, excluded
- LU 82 apprentice table → `apprentice_hourly` 18.12 for year 1, progression captured
- LU 129 "Journeyman Wireman Base Pay | $51.04 | $46.63 | $41.49" → a range, never
  an average
- Bounds: $956 and $0.0 → `implausible_value`
- `WAGE_DISPLAY = false` strips every wage string from both builds, grep-verified

## Task 6: rebuild and verify

1. Rebuild `out/frontend_data.json`, both finder builds, all 244 static pages.
2. ZIP index mismatches zero, the 12 sample ZIPs resolve, 244 unique slugs, zero
   dangling links.
3. All three config flags still strip cleanly: `SHOW_CONFIDENCE`, `STATUS_DISPLAY`,
   `WAGE_DISPLAY`.
4. Confirm no wage figure appears in any JSON-LD block.
5. Confirm no network call, `raw/` not written, `extraction_v2.csv` not written.
6. Confirm the page has **no external requests at all**. The map was rewritten as
   inline SVG specifically to achieve that and it must not regress.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Rejection counts by reason, out of 3,175. I expect `negative_context` and
   `insufficient_context` to account for most of `explicit_rate`.
2. Locals by tier: `display`, `review`, `reject`. **My estimate is that 40 to 80 of
   the 190 reach `display`.** Report the actual number and tell me if I am wrong.
3. `consistency_check` results, and every `fail` with its two conflicting figures.
4. The 15 `display` locals with the largest population, showing apprentice start,
   journeyman base, package, and effective date, so I can eyeball them against reality.
5. How many `display` locals have an `effective_date` older than 24 months. Those are
   the next thing to re-crawl.
6. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Re-crawling for fresher wage data. This round works from what is on disk. The
  effective-date report in item 5 is what will justify a paid crawl later.
- Changing `compute_status` or anything about application status.
- Hosting, domain, email backend, trademark.
