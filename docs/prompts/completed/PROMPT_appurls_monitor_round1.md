# Codex task: recover missing application links, operationalise the monitor

Working dir is `C:\Users\andre\ibew`. Zero paid API cost. One task needs plain HTTP
(free); everything else runs off files on disk.

## CONCURRENCY, read first

**A separate Claude agent may be running `PROMPT_status_round7.md` at the same time.**

It owns, and you must **NOT** touch: `compute_status.py`, `statement_evidence.py`,
`window_rules.py`, `out/round7_*.csv`.

You own everything else: `monitor.py`, `out/monitor_*`, `build_frontend_data.py`,
`build_page.py`, `build_local_pages.py`, `page_template.html`, the local page template,
all build output, and any new script you add.

**Do not run any git command.** No `add`, `commit`, `checkout`, `stash`. The other agent
owns git in this tree and concurrent commits have already produced a stale
`.git/index.lock` in this repo. Leave your work in the working tree and print, per task,
what changed and which files you touched. Andrew commits.

Reading git is fine (`git show`, `git diff`). Writing is not.

## HARD CONSTRAINTS

- **No Anthropic API calls. No Firecrawl. No re-extraction.** Never write
  `out/extraction_v2.csv`.
- **Do not run any `pass*.py` script.**
- Network is permitted **only** in task 3, and only plain `requests` GETs against URLs
  already in `out/monitor_state.json`. Nothing else, nowhere else.
- You may read `raw/` with targeted Python scans. Extract matches, discard the page
  body. Never dump HTML into context.
- Andrew is not available. Log blockers to `out/codex2_blockers.csv` and continue.
- 89 `compute_status.py` tests and 22 node tests must still pass. If either breaks,
  you touched something you do not own.

---

## Task 1: recover the 23 missing application URLs

**The biggest hole in the product.** 23 of 244 locals have no `application_url`, so the
page offers a visitor no way to apply. The largest:

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

**Every one of them has a JATC domain, which means its pages were crawled.** The URL is
almost certainly sitting in `raw/` and the extraction simply failed to lift it. This is
a free recovery, no crawling required.

Write `recover_application_urls.py`. For each of the 23, scan that local's already
crawled pages under `raw/` for candidate apply links:

- anchor `href`s whose text or URL contains apply, application, apprentice,
  applicant, enroll, register, intake, "how to apply", "start your application"
- forms posting to an application handler
- links to known third-party application hosts (e.g. tradeschoolinc, ApprenticeshipUSA,
  a state DOL apprenticeship portal, Google Forms, JotForm, Formstack)

Emit `out/application_url_candidates.csv`: `local_union_id`, `lu_number`,
`charter_city`, `population`, `candidate_url`, `anchor_text`, `source_file`,
`match_reason`, `rank`, `chosen`.

Rank candidates and pick at most one per local. Prefer, in order: a link on the local's
own apprenticeship page, a link whose anchor text says "apply", a third-party
application host, the apprenticeship page itself as a last resort.

**Do not invent URLs.** No guessing at `/apply` paths that were not observed in the
crawled HTML. If a local yields no candidate, leave it empty and report it. An empty
field is honest; a fabricated 404 is not.

Then feed the chosen URLs into `build_frontend_data.py` as a fallback layer: use
`extraction_v2.csv`'s `application_url` when present, otherwise the recovered one, and
add a boolean `app_url_recovered` to the bundle so a recovered link is distinguishable
from an extracted one. Report how many of the 23 you filled.

## Task 2: the literal string "False" in the website field

`website_corrected` contains the **string** `"False"` for most of the 23 locals above,
rather than an empty value. Something wrote a Python boolean into a text column.

Find every field across `out/*.csv` holding the literal strings `"False"`, `"True"`,
`"None"`, or `"nan"` where a URL, name, or date belongs. Report the count per file and
column. Normalise them to empty in the **build layer only** — do not rewrite the source
CSVs, and do not touch `extraction_v2.csv`. Add the guard to
`build_frontend_data.py` so it cannot reach the page.

Check whether any of these leaked into the 244 static pages as visible text.

## Task 3: make the monitor a real daily job

`monitor.py` has run **exactly once**, on 2026-08-11. `out/monitor_state.json` holds 219
records with `last_changed: null` on every one, and `out/monitor_changes.csv` and
`out/monitor_failures.csv` were never created. It has never diffed anything, which means
the freshness signal the whole status model is supposed to lean on does not exist yet.

Three things:

1. **Run the full sweep a second time.** 215 URLs, sequential, 1s sleep, roughly five
   minutes. This is the first real diff. Report: how many hashes changed, which locals,
   and confirm `out/monitor_changes.csv` and `out/monitor_failures.csv` now exist even
   if empty. **Do not call Firecrawl on a change.** Log it; Andrew reviews.
2. **Make it schedulable on Windows.** Write `run_monitor.bat` that cds to the repo,
   runs the sweep, and appends stdout and stderr to `out/monitor_log.txt` with a
   timestamp header. Keep the log to the last 60 runs. Then write
   `MONITOR_SETUP.md`: the exact Windows Task Scheduler steps to run it daily at 6am,
   in plain language, no jargon, written for someone who has not used Task Scheduler.
3. **Wire `last_changed` into freshness.** Add a `monitor_days_since_change` field to
   the bundle, computed per local from `monitor_state.json`. Do **not** feed it into
   `compute_status` — that file belongs to the other agent this round. Just surface it
   in the data so it is available, and note in `MONITOR_SETUP.md` that once three or
   four weeks of history exist, this becomes the real input to `is_stale`, which is
   still empty everywhere by design.

## Task 4: turn wage display off

Set `WAGE_DISPLAY = false` and rebuild. Reason, for the commit message Andrew will
write: only 8 of 244 locals reached the display tier, and four of those eight conflate
journeyman base with total package. LU 129 Lorain shows $65.66 inside its base range
when its own source text calls that figure "Total". LU 302 Martinez shows a journeyman
base of $26.50 to $27.30 in Contra Costa County, where the real figure is roughly
double, because the apprentice starting range populated the journeyman field.

Keep `wage_rules.py`, the tests, and `out/wage_reconciled.csv`. They are the input to a
future decision, not dead code. Leave `WAGE_DISPLAY` as a working switch.

Confirm by grep that no wage figure survives in either build or in any of the 244
static pages.

## Task 5: scope the wage crawl as a costed proposal

`out/wage_reconciled.csv` has 63 locals in the `review` tier: wage content exists but is
too messy to trust. Those are the pages worth fetching properly.

Write `out/wage_crawl_scope.csv`: `local_union_id`, `lu_number`, `charter_city`,
`population`, `tier`, `admitted_count`, `best_candidate_quote` (200),
`likely_wage_page_url`, `why_it_failed`.

`likely_wage_page_url` comes from links already observed in `raw/` pointing at wage,
pay, scale, rate, CBA, agreement, or benefits pages. Same rule as task 1: observed
only, never invented.

Then state plainly at the top of the file, as a comment: how many pages a targeted
crawl would need to fetch, and the population those locals cover. That is the number
that decides whether the crawl is worth paying for.

## Task 6: rebuild and verify

1. Rebuild `out/frontend_data.json`, both finder builds, all 244 static pages.
2. ZIP index mismatches zero. The 12 sample ZIPs still resolve: 02138, 10001, 60601,
   94110, 75201, 33101, 98101, 80202, 19104, 89101, 43201, 37201.
3. 244 unique slugs, zero dangling links.
4. All three flags still strip cleanly: `SHOW_CONFIDENCE`, `STATUS_DISPLAY`,
   `WAGE_DISPLAY`.
5. **Zero external asset requests** in either build. The map was rewritten as inline
   SVG specifically to achieve that and it must not regress. Grep for `http://` and
   `https://` in `src=` and `href=` attributes.
6. No wage figures in any JSON-LD block.
7. 89 `compute_status.py` tests pass, 22 node tests pass. You did not modify either.
8. List every file you modified.

## Report

Per task: what changed, the proving count, files touched. Then:

1. How many of the 23 missing application URLs you recovered, and the remaining gaps by
   population. Philadelphia at 2.23M is the one I care about.
2. Count of `"False"`/`"True"`/`"None"` string leaks by file and column, and whether any
   reached a static page.
3. Monitor second-sweep results: hashes changed, which locals, failures.
4. Confirmation that no wage figure appears anywhere in the built output.
5. From task 5: pages to crawl and population covered.
6. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- `compute_status.py`, `statement_evidence.py`, `window_rules.py`. Other agent.
- Any git command.
- Re-extraction, Firecrawl, paid crawls. Task 5 scopes one; it does not run one.
- Hosting, domain, email capture backend, trademark.
