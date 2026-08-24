# Claude Code task: IBEW finder, full build round

Working dir is this repo (`~/ibew`). Supersedes `PROMPT_frontend_round1.md`, which
was a shorter version of tasks 1 through 6 here. Eleven tasks. Zero paid API cost,
zero network. I am away for roughly an hour, work straight through.

## What already exists, do not recreate

- `city_coords.py` — charter city lat/lon for all 245 class-i targets, 245/245 matched.
- `build_frontend_data.py` — joins targets to computed status, OLMS membership,
  served population, inside-jurisdiction counties, ZIP index, city index.
  Emits `out/frontend_data.json` (1,267 KB).
- `page_template.html` — single-file UI, `__DATA__` placeholder for the payload.
- `build_page.py` — inlines the JSON, writes `ibew_finder.html` (1,288 KB).
- `compute_status.py` — 38 tests passing, `TODAY = 2026-08-10` in the test class.
- `window_rules.py` — `is_suspect_window()`.

Verified, take as given:

- ZIP index 34,135 entries, **zero** mismatches vs `out/zip_to_local.csv`, zero
  source ZIPs missing. City index 25,954 entries from `hud/zip_county.csv`.
- Status across 245: unknown 129, rolling 61, closed_pending 20, closed 13,
  conflicting 10, open 8, expired_data 4.
- 219 of 245 have `application_url`, 244 have OLMS membership, 20 have
  `next_open_date`, 181 have an evidence quote.
- `SHOW_CONFIDENCE` and `STATUS_DISPLAY` at the top of the script block, both `true`.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction. No network.** Everything
  here runs off files on disk. If a task seems to need a paid call, skip it, log it
  in `out/frontend_blockers.csv`, continue.
- **Do not run any `pass*.py` script.**
- You **may** read `raw/` this round, but only via targeted scans from Python.
  Extract matches, discard the body. Never dump page HTML into context.
- **Never write `out/extraction_v2.csv`.**
- I am not available. Do not stop to ask. Log blockers and keep moving.
- One commit per task. Rebuild and re-verify before each commit.
- Tasks 1 through 3 are data and gate everything else. Do them first, in order.

---

## Task 1: fix the LU 111 pin, audit the target list for the same error

`LU 111 Denver` is pinned with **zero inside counties and zero ZIPs**. It is an
outside/utility local. Denver's inside-wireman local is LU 68, which the ZIP lookup
for 80202 correctly returns. LU 111 must not be offered for an inside apprenticeship.

Probably not isolated. Competitor cross-validation found LU 1426 Grand Forks carrying
an **outside/lineman** application window as though it were the inside program.

Write `out/target_classification_audit.csv`: `local_union_id`, `lu_number`,
`charter_city`, `charter_state`, `trade_classes`, `inside_county_count`,
`inside_population`, `zip_count`, `has_i_class`, `suspect_flag`, `suspect_reason`.

Flag at minimum:

- zero inside counties or zero inside population
- `trade_classes` lacks `i`
- `trade_classes` has `o` or `u` but not `i`
- inside population more than an order of magnitude below the median for targets with
  comparable OLMS membership

Exclude anything with no inside jurisdiction from `build_frontend_data.py`. Print the
exclusions, do not drop them silently.

## Task 2: audit scoped closures

Never audited, surfaced by the competitor check. LU 313 Wilmington computes `closed`
/ high on:

> "No applications will be accepted in September 2026."

That is a one-month carve-out implying applications **are** accepted the rest of the
year. The competitor's "always accepting" is probably right.

Write `out/scoped_closure_audit.csv` over every `statement_type == 'closed'` statement
in `extraction_v2.csv`. Flag any whose text carries a scope limiter: a specific month,
a specific date, a named program other than inside wireman, a class or cohort year,
`except`, `other than`, `only`, `during`, `for the month of`, `until`.

Columns: `local_union_id`, `lu_number`, `charter_city`, `population`,
`verbatim_text` (300), `source_url`, `scope_limiter_found`, `current_status`,
`likely_misread`.

**Audit only. Do not change `compute_status`.** I want the size of the problem before
deciding between a rule and a re-extraction.

## Task 3: mine wage data from pages already on disk

`Apprentice pay` renders "Not yet collected" in both slots. It is probably the
highest-intent field on the page, and the competitor publishes journeyman scale per
local, so it is obtainable. You have 3,453 crawled local pages plus the JATC crawl in
`raw/`. Do the free deterministic pass before anyone pays to crawl.

Write `out/wage_candidates.csv`: `local_union_id`, `lu_number`, `source_file`,
`match_type`, `matched_text` (200 chars of surrounding context), `parsed_value`,
`confidence`.

`match_type` must distinguish at least:

- explicit hourly rate near wage vocabulary (`$NN.NN` within ~80 chars of wage, rate,
  scale, per hour, hourly, journeyman, apprentice)
- percentage-of-journeyman progression (`NN% of journeyman`, "starts at NN%")
- wage progression tables (repeated period/percentage or period/rate pairs)
- total package vs base wage. These are different numbers and must never be conflated.

**Do not write wage data into `frontend_data.json` and do not display it.** Regex over
raw HTML is exactly what produced the "Applicants Apply Online" defect. Report the hit
rate: how many of the 245 got at least one candidate, broken out by match type.

## Task 4: contact data cross-validation

15.9% of the IBEW directory's website fields were wrong, so assume phones and emails
are similarly unreliable. You can check them for free: the crawler independently
extracted `contact_email` and `contact_phone` per local into `extraction_v2.csv`.

Write `out/contact_validation.csv` comparing the directory tables
(`out/emails.csv`, `out/phones.csv`) against the crawled values per local:
`local_union_id`, `lu_number`, `directory_email`, `crawled_email`, `email_agreement`,
`directory_phone`, `crawled_phone`, `phone_agreement`, `recommended_value`,
`recommendation_basis`.

Normalize phone numbers to digits before comparing. `agreement` is one of `match`,
`mismatch`, `directory_only`, `crawled_only`, `neither`. `recommended_value` prefers
the crawled value when they disagree, because it came from the local's own live site.

Then use `recommended_value` in `build_frontend_data.py` instead of the raw crawled
field, and report the mismatch rate. If it is materially above 15.9%, say so, that
tells me the directory is worse than I assumed.

## Task 5: generate the 245 static local pages

This is the SEO asset and the reason the dataset is worth anything. Someone searching
"IBEW Local 134 apprenticeship" should land on a page, not a map.

Write `build_local_pages.py` emitting `site/local/<slug>.html`, one per surviving
local, where slug is `ibew-local-<lu>-<city>-<st>` lowercased and hyphenated
(e.g. `ibew-local-134-chicago-il`).

Each page must be **self-contained and lightweight**. Do not inline the 1.3 MB
payload. Each page gets only its own local's data, so pages should land in the
15 to 40 KB range.

Per page:

- Local number, city, state, JATC name
- Status block, governed by the same `SHOW_CONFIDENCE` / `STATUS_DISPLAY` flags
- `next_open_date` and the email-capture CTA when present
- Population served, national rank, OLMS membership, county count, ZIP count
- Requirements (min age, education, aptitude test) where present
- Official application link, local website, validated phone and email from task 4
- Full county list, and the ZIP list in a collapsed block
- Both CTAs, same as the finder
- A link back to the finder and to the 5 nearest other locals by great-circle
  distance from `city_coords.py`

SEO scaffolding on every page:

- `<title>` and meta description templated from real values, no filler
- canonical URL
- Open Graph and Twitter card tags
- JSON-LD structured data. Use `EducationalOccupationalProgram` with a
  `provider` of type `Organization`. Include `occupationalCategory` for
  electrician (SOC 47-2111) and the geographic area served.
- `<h1>` is the local name, headings nest properly

Also emit:

- `site/index.html` — the finder, built from `page_template.html`, with links into
  the local pages
- `site/sitemap.xml` — every local page, `lastmod` from the bundle's generated date
- `site/robots.txt` — allow everything, point at the sitemap

Note in a comment at the top of `build_local_pages.py`: trademark clearance on using
"IBEW" in a domain or product name is unresolved. Descriptive use in a page title
is a different question from a brand name, and I have not cleared either. Do not
pick a domain.

## Task 6: multi-local disambiguation

ZIP 02138 returns two locals (103 Boston, 96 Worcester). This is common at county
granularity and the current UI just lists them with no way to choose.

When a ZIP resolves to more than one local, show a comparison view instead of a plain
list: each candidate with its status, population served, `county_pct_coverage` and
`zip_confidence` from `zip_to_local.csv` (both are already in the source, surface them
in the bundle), and distance from the searched ZIP's city if derivable. Sort by
`res_ratio` descending so the most likely local is first, and label it.

Be honest in the copy: county-level jurisdiction means a ZIP can genuinely fall under
more than one local, and the user may need to call. Do not fabricate a single answer.

## Task 7: page hardening

In `page_template.html` and the local page template, then rebuild:

- **Mobile.** Below 900px the layout stacks but is untested. Map to 380px, search
  sticky at the top of the panel, detail panel fully scroll-reachable. Test at 375px
  and 768px.
- **Keyboard and a11y.** Result rows and pins are click-only. Make rows focusable and
  Enter-activatable, `aria-label` the markers, focus-trap the modal with
  Escape-to-close, label the email input. Contrast-check `--ink3` (#6b7889) on
  `--panel` (#151a22) and raise it if it fails WCAG AA for small text.
- **Failure states.** If Leaflet or the tile layer fails to load, the map is a blank
  dark box. Detect and render a message saying search still works.
- **The unknown problem.** 129 of 245 render "Status not published," so most of the
  map is gray. Give `expired_data` its own color instead of sharing with `unknown`,
  and add a map filter: all locals, or only confirmed status. Default to all.

## Task 8: lean build and performance

`ibew_finder.html` is 1,288 KB, nearly all payload. Add a `--lean` mode to
`build_page.py` that splits the bundle:

- inline only what first paint needs: the 245 locals with map and card fields
- move the ZIP and city indexes to `site/data/zips.json` and `site/data/cities.json`,
  fetched on first search
- keep a `--single` mode producing today's fully inlined file, because it works from
  `file://` with no server and that is how I will keep opening it

Report both sizes and confirm the single-file build still works with no server.

## Task 9: preserve the config flags

After every change, verify both remain single-constant switches requiring no other
edits, on the finder **and** on the 245 local pages:

- `SHOW_CONFIDENCE = false` removes every confidence badge and evidence quote, keeps
  status labels
- `STATUS_DISPLAY = false` removes status from map colors, legend, result rows, detail
  panel, and local pages, falling back to "check with the local" plus the official link

Build both variants to `/tmp` and confirm by grep that no confidence string and no
status label survives in the respective builds. Release requirement, not a nicety.

## Task 10: JS logic tests

The search and status-rendering logic has no tests. Extract the pure functions
(ZIP normalization, city matching, status label and note selection, multi-local
sorting) into `site/js/finder-core.js`, import it into the template, and write a
Node test file `test_finder_core.js` run with `node --test`.

Cover at minimum: ZIP zero-padding, sub-5-digit input, unknown ZIP, city prefix match,
city with no match, multi-local ordering by `res_ratio`, every status label, both flag
states. If Node is unavailable, log it as a blocker and skip only this task.

## Task 11: verification

1. Rebuild everything. Report file sizes for `ibew_finder.html`, the lean build, and
   the median and max local page.
2. Re-run the ZIP index cross-check against `out/zip_to_local.csv`. Mismatches must be
   zero. If task 1 excluded locals, state the new ZIP count and confirm the drop
   equals exactly the excluded locals' ZIPs.
3. These ZIPs must resolve to the same locals as before, except where task 1
   deliberately changed them: 02138, 10001, 60601, 94110, 75201, 33101, 98101, 80202,
   19104, 89101, 43201, 37201.
4. Confirm one static page per surviving local, that every slug is unique, and that
   every internal link resolves to a file that exists.
5. Validate the JSON-LD on three sample pages parses as JSON and has the required
   fields.
6. Confirm both flag variants build and strip correctly, on finder and local pages.
7. Confirm no network call and no write under `raw/`.

## Report

Per task: what changed, the proving count, the commit. Then:

1. Locals excluded by task 1, with city and population.
2. Scoped-closure count and the five largest by population.
3. Wage candidate hit rate by match type.
4. Contact mismatch rate, against the 15.9% website-field baseline.
5. Page count, median page size, total site size.
6. Final pin count and the status distribution behind it.
7. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Displaying wage data. Candidates only.
- Changing `compute_status`. Audits only, both this round.
- Hosting, domain selection, real email capture backend, analytics vendor.
- Trademark clearance. Flag it in code comments, do not resolve it.
- Re-extraction or any paid crawl.
