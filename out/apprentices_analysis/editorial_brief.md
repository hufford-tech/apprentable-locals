# RAPIDS Apprentices Analysis: Editorial Brief

Data snapshot: August 17, 2026  
Source: U.S. Department of Labor RAPIDS public-use extract  
Scope: 5,459,938 apprentice records, joined to 130,730 registered-program records  
Reproducible source hash (SHA-256): A622366A446F577E32F5639CC9C6A7F699681F224488D738F1197A9BA2A296CF

## Executive read

The dataset is usable and unusually rich, but it is not a spreadsheet. A chunked scan reproduced the source's documented 5,459,938 rows without loading the file into memory. The strongest near-term Apprentable stories are age at entry, long-run growth in starts, representation, and the scale of electrician apprenticeship.

The data also contains traps that can produce convincing but wrong claims: mixed wage units, extreme dates, a national/military ZA location bucket, duplicate column names, small numbers of duplicate apprentice IDs, and incomplete demographic fields. Outcomes and geographic rankings need more segmentation before publication.

## Official FY2025 system KPIs

These figures follow the DOL bulletin's definitions for the completed fiscal year October 1, 2024 through September 30, 2025:

| KPI | Count |
|---|---:|
| Active apprentices at period end | 696,129 |
| New apprentices | 314,550 |
| Exiters | 279,097 |
| Completed exiters | 122,522 |
| Cancelled exiters | 156,575 |
| Total apprentices served | 975,226 |

Completed exiters were 43.9% of FY2025 exiters and cancelled exiters were 56.1%. Those are official component counts, but the split should not be presented as a national "completion rate." It mixes occupations, program types, cohort ages, and military/civilian systems.

## Strongest findings

### 1. Apprenticeship starts are near a record high

- Calendar-year starts rose from 180,625 in 2015 to 314,317 in 2024: a 74.0% increase.
- Starts remained essentially level in 2025 at 313,971, just 0.1% below 2024.
- The series shows a clear 2020 disruption followed by a strong recovery.

Suggested headline: **Registered Apprenticeship Starts Are Up 74% Since 2015**

Editorial caution: the United Services Military Apprenticeship Program accounts for 56,885 FY2025 starts, or 18.1% of the national KPI. A finished article should show civilian and USMAP trends separately.

### 2. The typical apprentice begins in their mid-20s

- Median recorded age at start was 26 in 2025.
- The middle 50% began between ages 22 and 34.
- Exact age was valid for 313,716 of 313,971 calendar-year 2025 starts.
- Although the dictionary marks exact age as deprecated, it agreed with the official age-cohort field in all 5,341,417 comparable records.

Suggested headline: **The Typical Apprentice Is 26—Not 18**

This is the cleanest first article because it has a strong misconception-busting hook and requires little risky program matching.

### 3. Women's representation rose substantially

- Women were 10.6% of identified 2015 starts and 18.4% of identified 2025 starts.
- That is an increase of 7.8 percentage points.
- Sex was identified for 94.1% of 2025 starts.

Suggested headline: **Women Nearly Doubled Their Share of New Apprenticeships**

Editorial caution: the change should be decomposed by occupation. Some of the national increase may reflect growth in healthcare, technology, education, or other occupations rather than within-trade change.

### 4. Hispanic representation increased

- Hispanic or Latino apprentices were 23.6% of identified 2015 starts and 31.6% of identified 2025 starts.
- That is an increase of 7.9 percentage points.
- Ethnicity was identified for 261,033 of 313,971 calendar-year 2025 starts.

Suggested headline: **Nearly One in Three Identified New Apprentices Is Hispanic**

Editorial caution: show the missing/unidentified denominator and segment by occupation and geography.

### 5. Electrician is the largest apprenticeship occupation

Grouped by O*NET-SOC code, FY2025's leading occupations were:

| Occupation | New apprentices |
|---|---:|
| Electrician | 48,418 |
| Construction craft laborer | 22,078 |
| Plumber | 20,759 |
| Carpenter | 14,690 |
| Computer operator | 13,742 |
| Line maintainer / high-voltage electrician | 9,279 |

Electricians represented 15.4% of all FY2025 new apprentices before adding the separate line-maintainer occupation.

Suggested headline: **America Registered 48,000 New Electrician Apprentices in One Year**

### 6. Recorded hourly starting wages rose, but this needs a second analytical layer

- Among records explicitly flagged as hourly, the median reported starting wage rose from $15.31 in 2015 to $20.60 in 2025.
- That is a 34.6% nominal increase, not adjusted for inflation.
- The 2025 middle 50% ranged from $16.66 to $25.19.
- Valid hourly wage coverage was 217,994 records, or 69.4% of calendar-year 2025 starts.
- Among 1,086,333 completed records with valid hourly start and exit wages, the median recorded nominal increase was 55.4%.

Suggested headline after follow-up work: **What Registered Apprentices Earn When They Start—and How Pay Progresses**

Do not publish the trend without inflation adjustment and occupation/state controls. The source mixes hourly, weekly, monthly, quarterly, and annual wage units; this analysis uses only records explicitly marked hourly.

## Findings that need more work

### Outcomes

The current-status share among resolved historical exits is not an official completion rate. A publishable outcome analysis needs:

- Mature entry cohorts
- Occupation and program-type segmentation
- USMAP separated from civilian programs
- Treatment of transfers and reinstatements
- A clear observation window and right-censoring rules

### Geography

ZA contains national, military, and multi-state programs and accounts for 75,927 FY2025 starts, or 24.1% of the total. USMAP alone contributes 56,885. It must not be shown as a state or silently included in a state ranking.

Among ordinary state codes, California had 32,325 FY2025 new apprentices and Texas had 22,605. A finished geographic article should allocate or separately present national programs before comparing states.

### Union comparisons

The program UNION_Y_N field means union or CBA coverage; it does not uniquely identify IBEW construction JATCs. Union-versus-nonunion comparisons require the validated program classifier already being developed elsewhere in the project.

## Data-quality findings

- The source has 78 columns, and APPR_STATUS_REASON appears twice.
- There are 23 duplicate APPR_ID rows: about 4 per million. Deduplicate for exact record-level work.
- Start dates range from year 2 to year 2996; exit dates extend to year 9202.
- There are 526 future start dates and 32 future exit dates relative to the extract date. Future and pre-1900 dates were excluded from trends and KPI calculations.
- STARTING_WAGE is missing on 23.1% of records; EXIT_WAGE on 34.9%.
- Veteran status is missing on 19.9%; disability status on 21.9%; race on 7.2%; sex on 1.6%.
- Only 37 apprentice rows failed to map to a program state, so the program join itself is nearly complete.
- Status counts reconcile to the source after accounting for 992 null status values.
- Four RS status records remain unclassified and are too small to affect aggregates.

## Recommended publishing sequence

1. **The Typical Apprentice Is 26** — strongest and lowest-risk.
2. **Registered Apprenticeship Starts Are Up 74% Since 2015** — split USMAP from civilian programs first.
3. **Women Nearly Doubled Their Share of New Apprenticeships** — add occupation-level decomposition.
4. **America Registered 48,000 New Electrician Apprentices in One Year** — add state and union/JATC context.
5. **What Apprentices Earn When They Start** — inflation-adjust and control for occupation/state.
6. **Do Apprentices Complete Their Programs?** — hold until cohort methodology is complete.

## Methodology

- The original 3,012,472,052-byte CSV was read in 100,000-row chunks.
- Only 24 relevant columns were retained in memory.
- No individual apprentice records were written to output.
- New, active, exiter, and total-served counts follow the DOL KPI bulletin.
- Denied/incomplete registration codes DL, DR, IR, PR, and DU were excluded from new-start counts.
- Future dates and dates on or before January 1, 1900 were excluded from observed-start trends.
- Occupations were grouped by O*NET-SOC code to avoid double-counting alternate titles.
- Wage summaries require the hourly indicator, positive values, and values no greater than $100.
- Demographic percentages use identified records as the denominator and retain missingness counts separately.
