# Claude Code task: IBEW finder page, round 1

Working dir is this repo (`~/ibew`). A working prototype already exists and is
verified. Your job is to harden it and close three data gaps, not to rebuild it.

## What already exists, do not recreate

- `city_coords.py` — charter city lat/lon for all 245 class-i targets, 245/245 matched.
- `build_frontend_data.py` — joins targets to computed status, OLMS membership,
  served population, inside-jurisdiction counties, ZIP index, city index.
  Emits `out/frontend_data.json` (1,267 KB).
- `page_template.html` — the single-file UI, `__DATA__` placeholder for the payload.
- `build_page.py` — inlines the JSON into `ibew_finder.html` (1,288 KB).
- `ibew_finder.html` — the built page. Leaflet map, 245 pins sized by population and
  colored by status, ZIP and city search, per-local detail panel, two CTAs.

Verified state, take as given:

- ZIP index: 34,135 ZIPs, **zero** mismatches against `out/zip_to_local.csv`,
  zero source ZIPs missing.
- City index: 25,954 entries, derived from `hud/zip_county.csv`.
- Status across the 245: unknown 129, rolling 61, closed_pending 20, closed 13,
  conflicting 10, open 8, expired_data 4.
- 219 of 245 have an `application_url`, 244 have OLMS membership, 20 have a
  `next_open_date`, 181 have an evidence quote.
- Two config constants at the top of the script block: `SHOW_CONFIDENCE` and
  `STATUS_DISPLAY`. Both currently `true`. Flipping either must never require
  touching anything else. **Any change you make has to preserve that property.**

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl calls. No re-extraction. No network.**
  Every task below runs off files already on disk. If you think one needs a paid
  call, skip it, log it in `out/frontend_blockers.csv`, continue.
- **Do not run any `pass*.py` script.**
- You **may** read `raw/` this round, but only with grep-style targeted scans from
  Python, never by dumping page bodies into context. Task 3 needs it. Read files,
  extract matches, discard the body.
- **Never write `out/extraction_v2.csv`.**
- I am not available. Do not stop to ask. Log blockers and keep going.
- One commit per task. Rebuild and re-verify the page before each commit.

## Task 1: fix the LU 111 pin and audit the target list for the same error

`LU 111 Denver` is pinned on the map with **zero inside counties and zero ZIPs**.
It is an outside/utility local. Denver's inside-wireman local is LU 68, which the
ZIP lookup for 80202 correctly returns. LU 111 should not be offered to someone
looking for an inside apprenticeship.

This may not be isolated. During competitor cross-validation, LU 1426 Grand Forks
turned out to have an **outside/lineman** application window applied to it as though
it were the inside program.

Write `out/target_classification_audit.csv`, one row per target:
`local_union_id`, `lu_number`, `charter_city`, `charter_state`, `trade_classes`,
`inside_county_count`, `inside_population`, `zip_count`, `has_i_class`,
`suspect_flag`, `suspect_reason`.

Flag at minimum:

- zero inside counties or zero inside population
- `trade_classes` does not contain `i`
- `trade_classes` contains `o` or `u` but not `i`
- inside population is more than an order of magnitude below the median for targets
  with a comparable OLMS member count

Then exclude anything flagged as having no inside jurisdiction from
`build_frontend_data.py`, and print the exclusions. Do not silently drop them, I
want the list.

## Task 2: audit for scoped closures

Competitor cross-validation surfaced a defect class that has never been audited.
LU 313 Wilmington computes to `closed` / high on this verbatim text:

> "No applications will be accepted in September 2026."

That is a one-month carve-out. It implies applications **are** accepted the rest of
the year. Reading it as a global closure is wrong, and the competitor's "always
accepting" is probably the correct call.

Write `out/scoped_closure_audit.csv` over all statements in `extraction_v2.csv`
where `statement_type == 'closed'`. Flag any whose `verbatim_text` contains a scope
limiter: a specific month, a specific date, a named program other than inside
wireman, a specific class or cohort year, "except", "other than", "only",
"during", "for the month of", "until".

Columns: `local_union_id`, `lu_number`, `charter_city`, `population`,
`verbatim_text` (300), `source_url`, `scope_limiter_found`, `current_status`,
`likely_misread`.

**Audit only. Do not change `compute_status`.** I want to see the size of this
before deciding whether the fix is a rule or a re-extraction.

## Task 3: mine wage data from pages already on disk

`Apprentice pay` currently renders as "Not yet collected" in the detail panel, in
both slots. It is probably the highest-intent field on the page and the competitor
publishes journeyman scale per local, so it is obtainable.

You already have 3,453 crawled local pages plus the JATC crawl under `raw/`. Do a
free deterministic pass over them before anyone pays to crawl anything.

Write `out/wage_candidates.csv`: `local_union_id`, `lu_number`, `source_file`,
`match_type`, `matched_text` (200 chars of surrounding context), `parsed_value`,
`confidence`.

`match_type` should distinguish at least:

- explicit hourly rate near wage vocabulary (`$NN.NN` within ~80 chars of wage,
  rate, scale, per hour, hourly, journeyman, apprentice)
- percentage-of-journeyman progression (`NN% of journeyman`, "starts at NN%")
- wage progression tables (repeated period/percentage or period/rate pairs)
- total package vs base wage, these are different numbers and must not be conflated

Do **not** write wage data into `frontend_data.json` this round and do not display
it. Extraction from raw HTML with regex is exactly the kind of thing that produced
the "Applicants Apply Online" defect. I want to see the candidate list and the hit
rate first. Report: how many of the 245 got at least one candidate, by match type.

## Task 4: page hardening

In `page_template.html`, then rebuild:

- **Mobile.** Below 900px the layout stacks but has not been tested. Make the map
  380px, make the search sticky at the top of the panel, and make sure the detail
  panel is fully reachable by scroll. Test at 375px and 768px widths.
- **Keyboard and a11y.** Result rows and pins are click-only. Make result rows
  focusable and Enter-activatable, add `aria-label`s to the map markers, give the
  modal focus trapping and Escape-to-close, and make sure the email input is
  labelled. Contrast-check `--ink3` (#6b7889) on `--panel` (#151a22) and raise it
  if it fails WCAG AA for small text.
- **Empty and error states.** If Leaflet fails to load from the CDN, the map area
  is currently a blank dark box. Detect it and render a message telling the user
  search still works. Same for the tile layer.
- **The unknown problem.** 129 of 245 render as "Status not published," so more than
  half the map is gray. Right now unknown and `expired_data` share a color. Give
  `expired_data` its own treatment, and add a filter control to the map: show all,
  or only locals with a confirmed status. Default to all.

## Task 5: preserve the config flags

After every change, verify both of these still work as single-constant switches
with no other edits required:

- `SHOW_CONFIDENCE = false` removes every confidence badge and every evidence quote,
  keeps status labels.
- `STATUS_DISPLAY = false` removes status from the map colors, the legend, the result
  rows, and the detail panel, and falls back to "check with the local" plus the
  official application link.

Build both variants to `/tmp` and confirm by grep that no confidence string and no
status label survives in the respective builds. This is a release requirement, not
a nicety.

## Task 6: verification

1. Rebuild `out/frontend_data.json` and `ibew_finder.html`. Report both file sizes.
2. Re-run the ZIP index cross-check against `out/zip_to_local.csv`. Mismatches must
   be zero. If task 1 excluded any locals, the expected ZIP count will drop, state
   the new number and confirm the drop equals exactly the excluded locals' ZIPs.
3. Spot-check these ZIPs resolve to the same locals as before, except where task 1
   deliberately changed them: 02138, 10001, 60601, 94110, 75201, 33101, 98101,
   80202, 19104, 89101, 43201, 37201.
4. Confirm both flag variants build and strip correctly.
5. Confirm no network call and no write under `raw/`.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Locals excluded by task 1, with city and population.
2. Scoped-closure count from task 2 and the five largest by population.
3. Wage candidate hit rate from task 3, by match type.
4. Final pin count and the status distribution behind it.
5. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Displaying wage data. Candidates only this round.
- Changing `compute_status`. Audits only.
- Hosting, domain, real email capture backend, analytics, trademark clearance.
- Re-extraction or any paid crawl.
