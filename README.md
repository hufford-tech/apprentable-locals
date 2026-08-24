# IBEW Apprenticeship Finder

Address in, local out. 244 inside-wireman locals, 34,135 ZIP codes mapped to
jurisdictions, application status computed from each local's own website, journeyman
pay from federal Davis-Bacon wage determinations, and apprentice wage coverage from
local-published schedules and DOL RAPIDS registration wages.

## Open it

Double-click **`ibew_finder.html`**. Everything is inlined, there are zero external
requests, and it works offline.

For the version closest to a deploy, serve the `site/` folder:

```
cd site
python -m http.server 8000
```

## Rebuild after changing data or logic

```
python build_rapids_apprentice_wages.py
python build_frontend_data.py         # pass 1 -- population data only if
                                       # out/rapids_intake_estimate_by_lu.csv
                                       # doesn't exist yet on a cold checkout
python rapids_universe.py             # only if RAPIDS source data changed
python rapids_kpi.py                  # only if RAPIDS source data changed (needs apprentices.csv)
python rapids_kpi_join_locals.py      # only if RAPIDS source data changed
python rapids_intake_estimate.py      # reads frontend_data.json for population
python build_frontend_data.py         # pass 2 -- picks up the intake estimate
python build_page.py --single
python build_page.py --lean
python build_local_pages.py
```

`rapids_intake_estimate.py` reads `out/frontend_data.json` for jurisdiction
population, which is why `build_frontend_data.py` has to run once before it on
a cold checkout with no `out/rapids_intake_estimate_by_lu.csv` yet (population
doesn't change between rounds, so this is a one-time bootstrap, not a
steady-state two-pass requirement -- day to day, only the second
`build_frontend_data.py` run is needed after the RAPIDS scripts).

`build_local_pages.py` runs `check_links.py` as its last step: every internal
link in every generated artifact (`ibew_finder.html`, `site/index.html`,
`site/locals/*.html`) must resolve to a file that actually exists on disk, or
the build fails loudly. Run `python check_links.py` on its own to re-check
without rebuilding.

## Layout

```
ibew_finder.html          the single-file app, 2 MB, opens from disk
page_template.html        source template; ibew_finder.html is generated from it
site/                     lean build: index.html, 244 static local pages, sitemap
out/                      all generated data (CSV/JSON). Nothing here is hand-edited.
raw/                      cached source pages. Large. Never edited, only read.
docs/prompts/active/      agent task specs not yet run
docs/prompts/completed/   agent task specs already run, kept as an audit trail
archive/                  scripts that have served their purpose (see below)
```

### Active code, root level

**Core status engine.** Status is computed in Python from observations the extractor
recorded. The extractor never judges status. Do not reverse this.

| file | role |
|---|---|
| `compute_status.py` | the rule chain. 103 tests. Run `python compute_status.py`. |
| `statement_evidence.py` | admissibility gate: is a statement real evidence about intake? |
| `window_rules.py` | is a "window" an application window or just office hours? |

**Build.**

| file | role |
|---|---|
| `build_frontend_data.py` | joins everything into `out/frontend_data.json` |
| `build_page.py` | `--single` inlines all data; `--lean` splits it for hosting |
| `build_local_pages.py` | the 244 static SEO pages |
| `city_coords.py` | charter-city coordinates for the map |

**Pay (Davis-Bacon).**

| file | role |
|---|---|
| `pull_davisbacon.py` | fetches determinations from SAM.gov, caches to `raw/davisbacon/` |
| `parse_davisbacon.py` | parses rates, decomposes fringe, filters to inside wireman |
| `build_local_wage_davisbacon.py` | joins rates to locals |
| `wage_rules.py`, `build_wage_reconciled.py` | the earlier website-scraping approach, superseded but retained |

**Apprentice pay (RAPIDS/local schedules).**

| file | role |
|---|---|
| `build_rapids_apprentice_wages.py` | normalizes cached RAPIDS registration-time wages by local |
| `out/rapids_apprentice_wages.csv` | auditable local-level median and observed wage range |
| `rapids_universe.py` | the real IBEW/JATC RAPIDS program universe -- affirmative name signal required (see #11 below), reports what round 2's tightening dropped |
| `rapids_kpi.py` | Active/New Apprentices/Exiters per program from `apprentices.csv`, FY2025, forward-dated rows nulled out everywhere (not just period selection) |
| `rapids_kpi_join_locals.py` | joins the KPI numbers to `lu_number` by match type |
| `rapids_intake_estimate.py` | peer-based estimated annual intake -- confirmed figure for name-matched locals, population-bin median (rounded) for everyone else with a jurisdiction population, leave-one-out validated |

Apprentice source precedence in `build_frontend_data.py` is: reviewed local-published
schedule, RAPIDS registration-time wage, then an existing derived Davis-Bacon estimate.
RAPIDS values are labeled as registration-time observations and can include historical
cohorts; they are not presented as a current CBA scale.

**Issue reports.** `page_template.html` and the static local-page build include a
corner button that submits editable local context, issue type, details, page URL,
and an optional reply email to the `report-issue` Supabase Edge Function. Apply
`supabase/issue_reports_schema.sql`, deploy `supabase/functions/report-issue`, and
set these function secrets before deployment: `SUPABASE_SERVICE_ROLE_KEY`,
`RESEND_API_KEY`, `REPORT_ISSUE_TO_EMAIL`, and `REPORT_ISSUE_FROM_EMAIL`. Reports
are stored even if email delivery fails, with the delivery error retained on the
report row for manual follow-up. CORS is restricted to `https://apprentable.org`
and requests are rate-limited per IP via `check_rate_limit()`.

**Lead capture.** The "Notify me" forms on both surfaces post to the
`capture-lead` Edge Function, not directly to the `leads` table -- direct
anonymous insert is revoked (see `leads_schema.sql`). The function validates
email/phone format and field lengths, caps request size, silently discards
submissions where the hidden honeypot field is filled, and rate-limits per IP
via the same `check_rate_limit()` RPC as `report-issue`
(`supabase/rate_limit_schema.sql`). Apply `leads_schema.sql` and
`rate_limit_schema.sql`, deploy `supabase/functions/capture-lead`, and set
`SUPABASE_SERVICE_ROLE_KEY` before deployment. Email delivery for these leads
does not exist yet -- see "Known gaps."

**Monitoring.**

| file | role |
|---|---|
| `monitor.py` | hash-diffs each application URL to detect real changes |
| `monitor_noise_audit.py` | measures the false-positive rate |
| `run_monitor.bat`, `MONITOR_SETUP.md` | daily scheduling on Windows |

**Other.** `build_verify_worklist.py` (manual verification queue),
`build_shippable.py` (ZIP-level export), `test_*.py`.

### Archive

Nothing here runs as part of the pipeline. Kept for reproducibility.

| folder | contents |
|---|---|
| `archive/crawl/` | the original harvest and multi-pass crawl of 764 locals. Self-contained: `scrape_lib2.py` plus `pass0`–`pass5`. Re-running costs money. |
| `archive/one_off_builds/` | one-shot generators for `out/` files that already exist: census joins, ZIP crosswalk, population rebuild |
| `archive/audits/` | data-quality audits already run, each of which found and fixed something |
| `archive/round_diffs/` | before/after status diffs, one per fix round |

Archived scripts that import a core module carry a small `sys.path` insert at the top.
Run them from the repository root: `python archive/round_diffs/build_round7_status_diff.py`

## Things not to undo

These were each learned the hard way.

1. **The IBEW internal ID is the primary key, not the LU number.** LU numbers collide
   across entity types.
2. **The extractor records observations; Python decides status.** An LLM asked for a
   status will infer "accepting" from a window that lapsed months ago.
3. **`statement_type` labels are unreliable — 39.5% disagree with their own text.** That
   is why `statement_evidence.py` derives meaning from the text and lets the text win.
4. **A rate is not a rate.** `ELEC` classifications include lineman, residential,
   teledata, traffic signal and tunnel work. Mixing them showed Chicago a $51.14 base
   when the inside wireman rate is $57.75.
5. **Never range across different classifications.** A range that spans base and total
   package looks like a range and is a lie.
6. **Undated evidence loses to dated evidence.** But a recurring window that is open
   today counts as dated — that distinction is why Atlanta was briefly wrong in both
   directions.
7. **The `hidden` attribute loses to any CSS rule that sets `display`.** A permanently
   visible failure overlay hid a working map for two debugging rounds. There is now a
   global `[hidden]{display:none !important}`.
8. **Monitoring is hash-diff with plain requests.** 245 daily Firecrawl checks would be
   ~7,350 credits a month against a 10,000 annual budget.
9. **Population figures use `population_current`** (Census vintage 2024, Connecticut
   rebuilt from towns). The IBEW's own county figures are from the 2000 Census.
10. **Four display flags, each a one-line switch:** `SHOW_CONFIDENCE`,
    `STATUS_DISPLAY`, `WAGE_DISPLAY`, `RAPIDS_DISPLAY`. Never let status display
    become load-bearing.
11. **`RAPIDS_DISPLAY` defaults to `true` again as of round 2, but the confirmed
    and estimated tiers are two different jobs and must stay separate.** The
    round-1 false positive (a non-IBEW union electrical contractor's own
    number shown as if it were Local 716 Houston's) came from two compounding
    bugs, both now fixed: `rapids_universe.py` admitted `SPON_UNIONLABOR=1`
    alone with no name check (see `rapids_universe.py`'s docstring for the
    round-2 fix), and the site conflated city-matched programs with
    name-matched ones as if both were "this local's own number." Now: only
    `match_type=lu_number_match` (58 locals) feeds the full "Apprenticeship
    program size" detail block and the tile's `confirmed` value, unrounded.
    Every other local with a jurisdiction population gets `rapids_intake_estimate.py`'s
    population-bin median instead, rounded, tier `estimated`, visually
    distinguished (`.cell.est`, dashed accent border) and never shown as if it
    were that local's own reported figure. Do not merge these two code paths
    back together, and do not loosen `rapids_universe.py`'s name-signal
    requirement without re-running leave-one-out validation.

## Known gaps

- 14 of 244 locals still have no application URL, including LU 98 Philadelphia (2.23M).
- 159 locals have no Davis-Bacon union rate. This is structural: right-to-work states
  use survey averages, so LU 20 Dallas-Fort Worth (8.76M) has no union figure.
- Apprentice wage coverage currently reaches 158 of the 244 displayed locals: 6 reviewed
  local-published schedules and 152 RAPIDS-backed locals. RAPIDS is unavailable for the
  remaining locals until their program match or source schedule is validated; those pages
  show a clearly labeled national average benchmark instead of implying a local rate.
- `monitor.py` has a 24.7% ten-minute false-positive rate. Do not schedule it or feed
  `last_changed` into `is_stale` until that is fixed.
- Trademark clearance on using "IBEW" in a name or domain: not started.
- No alert-delivery worker exists yet. "Notify me" copy says alerts are launching
  soon and stores the lead (with `consent_at`/`unsubscribe_token`/`subscribed` on
  `leads`, ready for when delivery ships) -- it does not promise a specific send.
- RAPIDS-based annual intake is back on by default (`RAPIDS_DISPLAY=true`); see
  "Things not to undo" #11. Leave-one-out validation on the 58 name-matched
  locals: 42.5% median absolute percentage error (25th pctile 22.2%, 75th
  pctile 74.4%) -- the "usable but coarse" 35-60% band, published rounded to
  the nearest 10 with the stronger caveat wording. If `rapids_intake_estimate.py`
  is ever rerun and lands over 60% MdAPE, set `RAPIDS_DISPLAY` back to `false`
  by hand in both `build_page.py` and `build_local_pages.py`.
- The peer-based intake estimate assumes a city-matched program's population is
  the population of the local it matched to by city -- not a confirmed home
  local for that program, just a real registered program serving roughly that
  size of market. This is load-bearing for every `estimated`-tier value.
- Active-apprentice counts (the older "Apprenticeship program size" detail
  block) are shown only for the 58 name-matched locals now, not city-matched
  ones -- that was the same "wrong local's number" failure mode as intake,
  just not caught until round 2.
