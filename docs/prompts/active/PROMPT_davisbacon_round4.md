# Task: Davis-Bacon round 4 — county-scoped classifications, and the coverage ceiling

Working dir is `C:\Users\andre\ibew`. Continues `PROMPT_davisbacon_round3.md`.

Round 3 landed the important part: LU 302 Martinez at $66.26 base disproved the $26.50
scrape, Castroville and Amarillo agree with the scraped figures to the cent, and coverage
is 84 union inside rates. The source is validated.

This round fixes the three remaining wide ranges and answers whether more pulling is
worth it.

## Repo note

The tree was reorganised. Active code is in the root, prompts are in `docs/prompts/`,
and finished one-off scripts are under `archive/` with a `sys.path` shim at the top of
each. `README.md` documents the layout. Do not move anything.

## Ownership and constraints

You own: `parse_davisbacon.py`, `pull_davisbacon.py`,
`build_local_wage_davisbacon.py`, `test_davisbacon.py`, `out/davisbacon_*`,
`out/local_wage_davisbacon.csv`, `raw/davisbacon/`, `build_frontend_data.py`,
`build_local_pages.py`, `build_page.py`, `page_template.html`, all build output.

Do **not** touch `compute_status.py`, `statement_evidence.py`, `window_rules.py`,
`monitor.py`, `out/monitor_*`, or anything under `archive/`.

- **No Anthropic API calls. No Firecrawl. Never write `out/extraction_v2.csv`.**
- Network only against `sam.gov` and `dol.gov`. Cache to `raw/davisbacon/`.
- **No git commands.** Print files touched per task; Andrew commits.
- 103 `compute_status.py` tests and 22 node tests must still pass, untouched.
- Andrew is not available. Log blockers to `out/davisbacon_blockers.csv`, continue.

---

## Task 1: three wide ranges, three distinct causes

### LU 25 Long Island, $42.93 to $64.55, labelled `geographic` — wrong label

All three rows carry **identical** counties, "New York Counties of Nassau and Suffolk":

```
$64.55  ELEC0025-001  ELECTRICIAN                          <-- inside wireman
$42.93  ELEC0025-002  ELECTRICIANS: (TELEPHONE UNIT)
$49.79  ELEC0025-002  ELECTRICIANS: (MAINTENANCE UNIT)
```

Nothing geographic about it. Two classifications slipped the filter: `TELEPHONE UNIT`
and `MAINTENANCE UNIT`. The exclusion list has `MAINTENANCE AND REPAIR` but not bare
`MAINTENANCE UNIT`, and it has `TELEDATA`, `CATV` and `TELEVISION` but not `TELEPHONE`.

Add both. Expected result: a single $64.55.

**Also fix the label logic.** `range_basis = 'geographic'` must require that the rows
actually differ in geography. If the counties and the classification county-qualifiers
are identical, it is not geographic, and mislabelling it is what hid this.

### LU 193 Springfield, $24.83 to $39.80 — two escapes and a county mismatch

```
$39.80  ELEC0193-001  ELECTRICIAN (CASS, LOGAN, MACOUPIN (ATHENVILLE, SCOTTVILLE...))
$39.66  ELEC0193-012  ELECTRICAL LOW VOLTAGE WIRING INSTALLER: BUILDING
$24.83  ELEC0193-005  ELECTRICIAN Residential Construction (up to and including 4 stories)
                      counties: Illinois Counties of Sangamon
```

Two filter escapes. `ELECTRICAL LOW VOLTAGE WIRING INSTALLER` should have been caught by
the `LOW VOLTAGE` rule — find out why it was not, it may be a case-sensitivity or
word-boundary bug, and the same bug may be letting others through. And
`ELECTRICIAN Residential Construction (up to and including 4 stories)` is residential as
the primary scope; the round 3 trap rule was written for "including 4 STORIES
RESIDENTIAL" and does not catch this phrasing.

Then the harder problem: **Springfield IL is in Sangamon County**, and the only
Sangamon-scoped row is the residential one. The $39.80 row is scoped to Cass, Logan and
Macoupin, which are not Springfield's home county. So LU 193 may legitimately have **no
inside-wireman rate for its own jurisdiction**, and showing $39.80 would be showing a
neighbouring county's rate. Report what you conclude and prefer showing nothing over
showing the wrong county.

### LU 595 Dublin, $49.45 to $76.00 — genuinely geographic, wrong county selected

Here the counties column is identical across every row (the full multi-county list), but
**the geography is inside the classification text**:

```
$76.00  ELEC0595-001  ELECTRICIAN (ALAMEDA COUNTY)
$49.45  ELEC0595-002  ELECTRICIAN: ALL OTHER WORK (CALAVERAS AND SAN JOAQUIN COUNTIES)
$87.40  ELEC0595-001  CABLE SPLICER (ALAMEDA COUNTY)
$51.92  ELEC0595-002  ELECTRICIAN: TUNNEL WORK (CALAVERAS AND SAN JOAQUIN COUNTIES)
```

**Dublin is in Alameda County**, so the answer is $76.00, not a range reaching down into
Calaveras.

Implement county-qualifier extraction: parse any county names out of
`classification_text`, and when present, keep only rows whose qualifier intersects the
local's own inside counties from `out/jurisdictions.csv`. A range is legitimate only when
several qualifying rows all fall inside the local's jurisdiction.

Apply this everywhere, not just to LU 595. It will also settle LU 34 Peoria, whose
$35.00 to $45.65 spread is the Quincy and Peoria divisions, and LU 193 above.

### Also in LU 595: mangled classification text

Two rows read `OR EXCLUSION OF TERMINATIONS AND TESTINGS OF CONDUCTORS DETERMIN...` and
`CONDUCTORS DETERMINED BY THEIR FUNCTION; EXCLUDING FIRE ALARM WO...`. Those are
fragments — the parser is splitting a long classification description across rows and
losing the leading label. Find the split bug. A row whose text begins mid-sentence
cannot be classified reliably and must be flagged rather than silently admitted.

## Task 2: re-derive from cache and report the delta. No new requests.

Re-run parse and join with the task 1 changes against the existing cache. Report:

- LU 25 → expect single $64.55
- LU 595 → expect single $76.00 (Alameda)
- LU 193 → expect either no rate, or a clearly-labelled neighbouring-county rate, with
  your reasoning
- LU 34 Peoria → expect the Peoria-division rate alone if Peoria County is its home county
- how many of the 84 change, gain, or drop
- how many locals still exceed a 1.3x base range, tightened from 1.4x
- how many rows are now flagged for mangled text

Coverage may fall. A drop is the correct outcome if those locals had the wrong county's
rate.

## Task 3: the coverage ceiling

**LU 20 Dallas-Fort Worth, 8,760,827 people, the largest local in the dataset, has zero
building rows in the cache.** Not a survey row in building, nothing at all.

I need to know whether that is a gap or a ceiling, because it decides whether to keep
spending requests.

Write `out/davisbacon_coverage_analysis.csv`, one row per unmatched local:
`local_union_id`, `lu_number`, `charter_city`, `state`, `population`,
`is_right_to_work_state`, `determinations_cached_for_state`,
`elec_codes_seen_in_state`, `local_code_seen_anywhere`, `verdict`.

`verdict` should distinguish:

- `not_pulled` — we have few or no determinations for that state, more requests would help
- `no_union_rate_published` — determinations exist for the local's counties but carry
  survey classifications only, so there is no union rate to find at any budget
- `local_code_absent` — the state was pulled and other locals matched, but this local's
  `ELEC` code never appears

For Dallas specifically: confirm which Texas building determinations cover Dallas and
Tarrant counties, and what electrical classification they publish. If it is survey-only,
say so plainly — that is a structural ceiling, not a bug.

Then give me the headline: **of the 159 unmatched locals, how many are reachable with
more requests, and how many are structurally unreachable.** Weight both by population.

## Task 4: spend up to 150 more requests, only where task 3 says it helps

Only pull states where the verdict is `not_pulled`, ordered by unmatched population.
Report the coverage curve and the final count. Stop early if two consecutive states add
nothing.

## Task 5: tests, display, verify

Unit tests for every new exclusion (`TELEPHONE UNIT`, `MAINTENANCE UNIT`, residential
up-to-4-stories phrasing, the low-voltage escape), for county-qualifier extraction
including the LU 595 and LU 34 cases, and for mangled-text detection. Plus a regression
test that LU 302, 134, 3, 569, 98, 613, 38, 234 all keep their round 3 figures.

Display unchanged, still behind `WAGE_DISPLAY`. Where a rate comes from a county other
than the local's home county, either omit it or label it explicitly with the county. Do
not show a neighbouring county's wage as if it were the local's.

Verify: rebuild everything, ZIP mismatches zero, the 12 sample ZIPs resolve, 244 unique
slugs, zero dangling links, all three flags strip cleanly, zero external asset requests,
no wage figures in JSON-LD, 103 + 22 tests pass, second parse makes zero network
requests.

## Report

1. LU 25, LU 595, LU 193, LU 34: final figures and reasoning.
2. Why the `LOW VOLTAGE` rule missed `ELECTRICAL LOW VOLTAGE WIRING INSTALLER`, and
   whether the same bug let anything else through.
3. Coverage before and after: gained, changed, dropped.
4. **Task 3 headline: reachable versus structurally unreachable, by count and by
   population.**
5. Dallas: what Texas actually publishes for its counties.
6. Locals still over 1.3x, and rows flagged for mangled text.
7. The mangled-text split bug: what it was.
8. Anything you found that I have not accounted for.

No summary document.
