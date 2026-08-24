# Task: RAPIDS round 1 — identify the real JATC universe, then join to the 244 locals

Working dir is `C:\Users\andre\ibew`. New data source, and it supersedes the wage work.

## The data

DOL RAPIDS extract, in the uploads folder. Copy it into `raw/rapids/` before working, and
never modify the originals.

| file | rows | contents |
|---|---|---|
| `programs.csv` | 130,778 | one row per registered program: name, city, state, ZIP5, `ACTIVE_APPRCT`, `UNION_Y_N`, `ORG_TYPE`, `SPON_*` flags, `EIN`, `REGISTERED_DT`, `PROB_LENGTH`, `RTI_LENGTH` |
| `occ-prog-bridge.csv` | 201,063 | program-to-occupation, with `OCCUP_TITLE`, `ONET_SOC_CD`, `JRNYMAN_WAGE`, `TERM_LENGTH_MIN/MAX` |
| `apprentices.csv` | 5,459,938 | **2.9 GB.** One row per apprentice: `PS_ID`, `APPR_STATUS_CD`, `START_DT`, `STARTING_WAGE`, `EXIT_WAGE`, `AGE_AT_START`, `EDUCATION_CD`, demographics |
| `additional program info.csv` | 130,197 | `IS_CBA`, `IS_SINGLE_EMP`, `IS_MULTI_EMP`, `SEL_PROCS`, `DBA` |
| `rti providers.csv` | 129,485 | classroom training providers per program-occupation |
| `location data.csv` | 39,538 | ZIP to county FIPS crosswalk |
| `data_dictionary_06-17-2026.xlsx` | | **read this first** |
| `draft Bulletin ... KPI Calculations in Registered Apprenticeship.docx` | | DOL's own definitions for completion and retention rates. **Use their formulas, not invented ones.** |

## Two errors in my initial read. Do not inherit them.

I looked at this quickly and got two things wrong. Correcting them is task 1.

**Error 1: `UNION_Y_N = 1` is not the IBEW universe.** It yields 1,178 inside-electrician
programs, and I called that "your universe". It is not. Sampling the names that lack a
local number shows what is actually in there:

```
Morton Salt Inc.                                    Loreauville LA
Hawaii Electric Light Company                       Hilo HI
Princeton University Facilities Department          Princeton NJ
City of Battle Creek                                Battle Creek MI
Howard County Government Joint Apprenticeship Cmte  Ellicott City MD
Lawrence Township Public Schools                    Lawrence NJ
Office of Facilities Management and Reliability     Washington DC
WESTERN IOWA POWER COOPERATIVE LU55                 Denison IA
```

Those are **in-house maintenance-electrician programs at unionised employers**. Union
shops, not IBEW construction JATCs. A salt plant's electrician program has nothing to do
with an inside wireman apprenticeship.

**This means the 63.1% completion rate I quoted is computed over a contaminated set and
must not be used or published.** Recompute it once the real universe is defined.

**Error 2: `SEL_PROCS` is empty.** I said it would tell us which programs use an aptitude
test. It is populated for **0 of 1,178** programs. Check whether `SEL_PROCS_3URI`,
`IS_SEL_PROC` or `SEL_PROC_DATE` carry anything usable, and if not, say so plainly. Do not
build anything on that field.

Also correcting my own optimism: only **84 of 1,178** program names contain an extractable
local number. Name-based joining alone is weak.

## Ownership and constraints

You own: `raw/rapids/`, `out/rapids_*`, and any new `rapids_*.py` script.

Do **not** touch `compute_status.py`, `statement_evidence.py`, `window_rules.py`,
`monitor.py`, or anything under `archive/`. Do **not** touch build scripts, page
templates, or build output this round — nothing reaches the site until the join is
validated.

- No Anthropic API calls, no Firecrawl, no network at all. Everything is local.
- Stream `apprentices.csv`; never load it into memory. A full scan takes a few minutes and
  filtering by a `PS_ID` set is fast.
- No git commands. Print files touched per task; Andrew commits.
- 103 `compute_status.py` tests and 22 node tests must still pass, untouched.
- Andrew is unavailable. Log blockers to `out/rapids_blockers.csv` and continue.

---

## Task 1: define the IBEW construction JATC universe. Report before proceeding.

**Stop and report after this task.** Everything downstream is worthless if the universe
is wrong, and I have already made that mistake once this round.

Start from inside-electrician occupations: `OCCUP_TITLE` containing
`INTERIOR ELECTRICIAN` or equal to `ELECTRICIAN`. Verify against the data dictionary that
this is the right occupation set, and check `ONET_SOC_CD` — inside wireman should map to
`47-2111.00`. Report what the actual SOC distribution looks like.

Then separate real JATCs from in-house employer programs. Candidate discriminators, and I
do not know which works best:

- `ORG_TYPE` and `OTHER_ORG_TYPE`
- the `SPON_*` flag family: `SPON_EMPLOYER`, `SPON_UNIONLABOR`, `SPON_BSNSSASSCTN`,
  `SPON_INTERMEDIARY`, `SPON_CMMNTYCLLGUNIV`. Note `SPON_UNIONLABOR = 1` on only 174
  programs, which is far too few, so it is not sufficient alone.
- `IS_MULTI_EMP` versus `IS_SINGLE_EMP`. A construction JATC serves many contractors; an
  in-house program serves one employer. **This may be the cleanest signal available.**
- `IS_CBA`
- `NAICS_CD` and `SIC_CD` — electrical contractors versus manufacturing, government, education
- name patterns: `IBEW`, `JATC`, `JATF`, `JAC`, `NECA`, `ELECTRICAL TRAINING`,
  `ELECTRICAL WORKERS`, `ELECTRICAL JOINT`
- negative name patterns: `CITY OF`, `COUNTY`, `TOWNSHIP`, `SCHOOL`, `UNIVERSITY`,
  `COLLEGE`, `HOSPITAL`, `COOPERATIVE`, `POWER COMPANY`, `INC.`, `LLC`, `CORP`

Build a scored classifier, not a single rule. Emit `out/rapids_jatc_universe.csv` with one
row per candidate program: identifiers, name, city, state, ZIP5, `ACTIVE_APPRCT`, every
discriminator value, a score, a `verdict` of `jatc` / `in_house` / `uncertain`, and the
reasons.

Report:

- how many programs land in each verdict
- the total `ACTIVE_APPRCT` for the `jatc` set
- **20 sampled names from each verdict so I can eyeball whether the classifier is right.**
  This is the check that matters.
- whether `IS_MULTI_EMP` alone would have got there

Sanity anchors. These are real IBEW JATCs and must all come out `jatc`:
`ATL ELECTRICAL JATC` (Norcross GA, 2,708 apprentices), `IBEW-NECA ELECTRICIANS #134 JATF`
(Alsip IL, 1,825), `Los Angeles County Electrical JATC` (1,840),
`North Texas Electrical JATC` (Grand Prairie TX, 873),
`Electrical Training Institute (LU 481)` (Indianapolis, 1,135),
`Jac Ibew Electrical Lu #3` (Flushing NY, 1,436), `IBEW 99 JATC` (Cranston RI).

And these must all come out `in_house`: `Morton Salt Inc.`,
`Hawaii Electric Light Company`, `Princeton University Facilities Department`,
`City of Battle Creek`, `Lawrence Township Public Schools`.

## Task 2: join the JATC set to the 244 locals

Four join paths. Use all of them, then reconcile and score confidence.

1. **Local number in the program name.** Patterns seen: `LU 481`, `#134`, `LOCAL 26`,
   `Lu #3`, `IBEW 99`. Only ~84 hit, but they are the highest-confidence matches.
2. **`PROG_ZIP5` against `out/zip_to_local.csv`.** 938 distinct ZIPs across the union set.
   A JATC's office ZIP falling in a local's jurisdiction is strong evidence.
3. **County**, via `location data.csv` ZIP-to-FIPS then `out/jurisdictions.csv` inside rows.
4. **Name against the JATC names we already extracted.** `out/extraction_v2.csv` has
   `jatc_name` and `jatc_domain` per local, scraped from the locals' own websites. Fuzzy
   match `PROG_NAME` against `jatc_name`. This is an independent source and agreement
   between it and path 1 or 2 is the strongest signal available.

Emit `out/rapids_local_match.csv`: `local_union_id`, `lu_number`, `charter_city`,
`population`, `ps_id`, `prog_name`, `prog_city`, `prog_state`, `prog_zip5`,
`active_apprct`, `match_paths`, `match_confidence`, `conflicts`.

A local may legitimately match several programs — locals register inside, residential and
VDV separately, and multi-state locals register per state. Keep them all, flag which is
the primary inside-wireman program by `ACTIVE_APPRCT`.

Report the match rate: how many of 244 matched, at what confidence, and the population
covered. Then the reverse: how many `jatc` programs matched no local, and what they are —
those are either locals outside the 244 or classifier errors.

## Task 3: per-local metrics from the apprentice records

Stream `apprentices.csv` once, filtering to the matched `PS_ID` set.

**Use the DOL KPI bulletin's definitions.** Read the docx first. Do not invent a
completion-rate formula; if the bulletin specifies a cohort window or an exclusion rule,
follow it and cite the section.

Per local, emit `out/rapids_local_metrics.csv`:

- `active_apprentices` (from `ACTIVE_APPRCT` and from a live count of `APPR_STATUS_CD`,
  reported separately — if they disagree, say so)
- completed, cancelled, still-registered counts
- `completion_rate` per the bulletin, with the denominator stated in a column
- `cancellation_rate`
- median `STARTING_WAGE`, median `EXIT_WAGE`, and the spread between them
- median `AGE_AT_START`
- median time from `START_DT` to completion
- `JRNYMAN_WAGE` from the occupation bridge
- cohort size by registration year for the last 10 years, so I can see whether a program
  is growing or shrinking

Decode `APPR_STATUS_CD` from the data dictionary. Observed values include `CO`, `CA`,
`RE`, `DL`, `DU`, `RI`, `PR`, `SU`, `DR`, `IR` — do not guess at the rare ones.

**Report the national completion rate for the clean JATC set**, and say explicitly how it
differs from the 63.1% I computed over the contaminated set.

## Task 4: cross-validate against everything we already have

Free validation, and it tells us whether the join is real:

- `JRNYMAN_WAGE` versus the Davis-Bacon figures in `out/local_wage_davisbacon.csv` for the
  84 locals with both. Agreement within 15% on a decent share means both are right.
  Specifically check LU 302 Martinez (DB says $66.26), LU 134 Chicago ($57.75),
  LU 98 Philadelphia ($70.97), LU 613 Atlanta ($38.65).
- `ACTIVE_APPRCT` versus `olms_members` in `out/targets_with_population.csv`. Apprentices
  should be a plausible fraction of membership, roughly 5 to 15%. Flag outliers both ways.
- `PROG_CITY` versus `charter_city`. Disagreements are not necessarily errors, JATCs are
  often in suburbs, but a different state is a red flag.
- RTI providers versus the `jatc_domain` values we scraped.

Report every material disagreement. A join that produces wages contradicting Davis-Bacon
on most locals is a broken join.

## Task 5: report, no site changes

Nothing goes on the site this round. The deliverables are the three CSVs and the report.

1. Task 1 verdict counts, the 20 samples per verdict, and whether every sanity anchor
   landed correctly.
2. Match rate against the 244, by confidence, and population covered.
3. **National completion rate for the clean set, versus my contaminated 63.1%.**
4. The five largest locals by population, with active apprentices, completion rate,
   starting wage, journeyman wage.
5. Cross-validation results against Davis-Bacon and OLMS membership.
6. Whether `SEL_PROCS` or any sibling field carries selection-procedure content.
7. What is in `apprentices.csv` that I have not asked about and should have.
8. Anything you found that I have not accounted for.

No summary document.

## Out of scope

- Any change to the site, build scripts, page templates, or `compute_status.py`.
- Publishing completion rates. This round establishes whether the numbers are sound.
- `PROMPT_davisbacon_round4.md`. Shelved; `JRNYMAN_WAGE` is a better source. Do not run it.
