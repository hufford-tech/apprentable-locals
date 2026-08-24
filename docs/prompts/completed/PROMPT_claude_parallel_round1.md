# Claude Code task: application URL recovery, monitor, and one status fix

Working dir is `C:\Users\andre\ibew`.

## CONCURRENCY, read first

**Codex is running `PROMPT_davisbacon_round2.md` right now.** It owns all build scripts,
all page templates, all build output, and the wage display path.

You own, and may modify:

- `recover_application_urls.py` (new)
- `monitor.py`, `run_monitor.bat` (new), `MONITOR_SETUP.md` (new)
- `compute_status.py` and its tests
- `out/application_url_candidates.csv`, `out/string_leak_audit.csv`,
  `out/monitor_*`, `out/round8_*` (all new)

You must **NOT** touch, for any reason:

- `build_frontend_data.py`, `build_page.py`, `build_local_pages.py`
- `page_template.html`, the local page template, `site/local.css`, `site/js/*`
- `ibew_finder.html`, `site/index.html`, `site/local/*.html`, `out/frontend_data.json`,
  `site/data/*.json`
- `parse_davisbacon.py`, `out/davisbacon_*`, `out/local_wage_davisbacon.csv`,
  `raw/davisbacon/`, `test_davisbacon.py`
- `wage_rules.py`, `out/wage_*.csv`

**Do not rebuild anything.** Your job is to produce data files, scripts, and a
`compute_status.py` change. Codex rebuilds; Andrew runs a final integration step after
both of us finish.

**You own git in this tree.** Codex has been told not to touch it. Commit your work,
prefix every message with `parallel:`. If you hit a `.git/index.lock` that is more than
a few minutes old with no live git process, it is stale from an earlier session and you
may remove it.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction.** Never write
  `out/extraction_v2.csv`.
- **Do not run any `pass*.py` script.**
- Network permitted **only** in task 3, and only plain `requests` GETs against URLs
  already present in `out/monitor_state.json`. Do not fetch `sam.gov` or `dol.gov`;
  Codex is working those hosts.
- You may read `raw/` with targeted Python scans. Extract matches, discard the page
  body. Never dump HTML into context.
- Andrew is not available. Log blockers to `out/round8_blockers.csv` and continue.
- 100 `compute_status.py` tests must pass at the end, plus whatever you add.

---

## Task 1: recover the 23 missing application URLs

**The biggest hole in the product.** 23 of 244 locals have no `application_url`, so
their page gives a visitor no way to apply. The largest:

```
LU   98  Philadelphia     2,234,345   jatc www.ibew98.org
LU  342  Winston-Salem    2,003,754   jatc www.ibew342.org
LU  177  Jacksonville     1,791,176   jatc www.ibew177.org
LU   76  Tacoma           1,502,901   jatc www.ibew76.org
LU  363  New City         1,457,876   jatc ibewlu363.org
LU 1186  Honolulu         1,446,065   jatc www.hetf1186.org
LU  295  Little Rock      1,259,461   jatc www.ibew295.org
LU  130  New Orleans      1,233,922   jatc ibewlu130.com
LU   90  New Haven          966,269   jatc jatc90.org
LU  527  Galveston          917,088   jatc www.ibew527.com
LU  453  Springfield        809,153   jatc www.ibew453.com
LU  934  Kingsport          791,065   jatc ibew934.com
LU  364  Rockford           607,246   jatc www.ibew364.org
LU  309  Collinsville       559,486   jatc www.ibew309.com
```

**Every one of them has a JATC domain, meaning its pages were already crawled.** The URL
is almost certainly sitting in `raw/` and the extraction failed to lift it. This is a
free recovery. No crawling.

Write `recover_application_urls.py`. For each of the 23, scan that local's crawled pages
under `raw/` for candidate apply links:

- anchor `href`s whose href or anchor text contains apply, application, apprentice,
  applicant, enroll, register, intake, "how to apply", "start your application"
- forms posting to an application handler
- links to known third-party application hosts, e.g. tradeschoolinc,
  ApprenticeshipUSA, a state DOL apprenticeship portal, Google Forms, JotForm,
  Formstack

Emit `out/application_url_candidates.csv`: `local_union_id`, `lu_number`,
`charter_city`, `population`, `candidate_url`, `anchor_text`, `source_file`,
`match_reason`, `rank`, `chosen`.

Rank and pick at most one per local. Prefer, in order: a link on the local's own
apprenticeship page, a link whose anchor text says "apply", a third-party application
host, the apprenticeship page itself as a last resort.

**Do not invent URLs.** No guessing at `/apply` paths that were not observed in crawled
HTML. If a local yields nothing, leave it empty and report it. An empty field is honest;
a fabricated 404 is worse than nothing.

**Do not wire this into the build.** Codex owns `build_frontend_data.py`. Produce the
CSV and document, at the top of the file as a comment, exactly which column the build
should read and what the fallback precedence must be. Andrew wires it after.

## Task 2: the literal string "False" leak

`website_corrected` contains the **string** `"False"` for most of those 23 locals rather
than an empty value. A Python boolean was written into a text column.

Audit every `out/*.csv` for fields holding the literal strings `"False"`, `"True"`,
`"None"`, or `"nan"` where a URL, name, or date belongs. Emit
`out/string_leak_audit.csv`: `file`, `column`, `literal`, `row_count`, `sample_lu`.

Report the count per file and column, and check whether any reached the 244 static pages
as visible text. **Report only. Do not fix it in the build layer** — that is Codex's
file. Note the recommended guard in your report so Andrew can apply it.

## Task 3: make the monitor a real daily job

`monitor.py` has run **exactly once**, on 2026-08-11. `out/monitor_state.json` holds 219
records with `last_changed: null` on every one, and `out/monitor_changes.csv` and
`out/monitor_failures.csv` were never created. It has never diffed anything, which means
the freshness signal the entire status model is meant to lean on does not exist.

1. **Run the full sweep a second time.** 215 URLs, sequential, 1 second apart, roughly
   five minutes. This is the first real diff. Report how many hashes changed, which
   locals, and confirm both CSVs now exist even if empty. **Do not call Firecrawl on a
   change.** Log it; Andrew reviews.
2. **Make it schedulable on Windows.** Write `run_monitor.bat`: cd to the repo, run the
   sweep, append stdout and stderr to `out/monitor_log.txt` with a timestamped header,
   and keep the log to the last 60 runs. Then write `MONITOR_SETUP.md` with the exact
   Windows Task Scheduler steps to run it daily at 6am, in plain language, written for
   someone who has never opened Task Scheduler.
3. **Expose the freshness signal without wiring it in.** Emit
   `out/monitor_freshness.csv`: `local_union_id`, `lu_number`, `url`, `last_checked`,
   `last_changed`, `monitor_days_since_change`, `consecutive_failures`. Note in
   `MONITOR_SETUP.md` that once three or four weeks of history exist, this becomes the
   real input to `is_stale`, which is empty everywhere today by design.

Do **not** feed this into `compute_status`. It is not ready and the history does not
exist yet.

## Task 4: LU 613 is open and does not say when it closes

Round 7 got Atlanta to `open`, correctly. But:

```
LU 613 Atlanta, 7,903,227 people -> open / medium, inferred_window_status=True
  recurring window: open_month 8, open_day 1, close_month 8, close_day 31
  next_open_date  = (empty)
  next_close_date = (empty)     <-- should be 2026-08-31
```

Its window closes on August 31, nineteen days from `TODAY`. "Open now, closes August 31"
is the single most actionable line you could put in front of an Atlanta visitor, and it
is missing because the recurring-resolution path populates `next_open_date` for
`closed_pending` but never populates `next_close_date` for `open`.

Fix it in `compute_status.py`: when a resolved recurring window is the basis for `open`,
populate `next_close_date` from that window's computed end. Same for a resolved absolute
window with a real `close_date`.

Guards that must not move: the round 7 assertion that no record emits
`next_open_date == next_close_date` must still hold and still be tested. LU 567 Portland
keeps `next_close_date` empty. LU 538, LU 490, LU 12, LU 130, LU 292, LU 26, LU 520,
LU 1340 all unchanged.

Add tests: LU 613 gets `next_close_date` 2026-08-31, and report how many other locals
gain a `next_close_date`.

## Task 5: verify. No rebuild.

1. Full `compute_status.py` suite, paste the output. 100 existing tests plus yours.
2. Run the 242-record loop, print the distribution, confirm nothing raises and confirm
   zero `next_open_date == next_close_date` collisions.
3. `out/round8_status_diff.csv` for task 4's change, before-state from the git blob at
   the commit you started from.
4. Confirm a second `parse`-free monitor run reads state correctly.
5. List every file you modified. Confirm you touched nothing outside your ownership
   list, did not rebuild, and did not fetch `sam.gov` or `dol.gov`.

## Report

Per task: what changed, the proving count, the commit. Then:

1. How many of the 23 application URLs you recovered, and the remaining gaps by
   population. Philadelphia at 2.23M is the one that matters most.
2. String-leak counts by file and column, and whether any reached a static page.
3. Monitor second sweep: hashes changed, which locals, failures.
4. LU 613's `next_close_date`, and how many other locals gained one.
5. The exact integration steps Andrew must run after Codex finishes, as a numbered list.
   You and Codex have both produced things that need wiring into the build, and you are
   the one who can see what yours needs.
6. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Any build script, page template, or build output. Codex owns all of it.
- Anything under `raw/davisbacon/` or `out/davisbacon_*`.
- Feeding monitor freshness into `compute_status`. Not yet.
- Hosting, domain, email capture backend, trademark.
