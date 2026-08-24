# State DOL / apprenticeship-agency recruitment-notice inventory

Top 15 states by target count: CA(20), IL(17), OH(17), NY(14), PA(13), TX(11), MI(10), IN(10), WI(9), FL(8), MO(6), TN(6), NJ(6), IA(6), WA(5).

Inventory only -- nothing harvested.

| State | Agency | URL | Browsable index? | Explicit start/end dates w/ year? | Scrapeable? |
|---|---|---|---|---|---|
| NY | NYS DOL | https://dol.ny.gov/apprenticeship/apprenticeship-announcements | **Yes** -- 73 results, paginated, filterable by region | **Yes** -- e.g. "Electricians JAC Buffalo LU #41: Opening 10/07/2026, Closing 09/29/2027" | **Yes** -- static server-rendered HTML, no JS gate |
| IL | IL Dept. of Commerce / IllinoisWorkNet | https://www.illinoisworknet.com/ApprenticeshipIL/Pages/Announcements.aspx | No -- landing/nav hub, no notices rendered on the page itself | Unknown -- notices (if any) live elsewhere in the site, not surfaced here | Static shell, but no content to scrape at this URL |
| OH | ApprenticeOhio / OhioMeansJobs | https://omj.ohio.gov/program/index.stm | Domain did not resolve at check time; no dated-notice index found via search | No | Unconfirmed -- needs re-check, but no evidence of a notice index |
| PA | PA Apprenticeship & Training Office (ATO) | https://www.pa.gov/agencies/dli/... | No statewide notice index found; recruitment info lives on individual JATC sites (e.g. WCPA EJATC, IEC PA) not a central DOL page | N/A | N/A |
| CA | Division of Apprenticeship Standards (DIR) | https://www.dir.ca.gov/das/ | No -- "Program Search" tool only, not a dated-notice feed | No | N/A (search tool, not a notice list) |
| TX | ApprenticeshipTexas (TWC) | https://www.twc.texas.gov/services/job-training/find-apprenticeships | No -- informational page, redirects to federal apprenticeship.gov finder | No | Static HTML but no notices to scrape |
| MI | LEO Registered Apprenticeship | https://www.michigan.gov/leo/bureaus-agencies/wd/apprenticeships | No dated index found; contact-based (email LEO-Apprenticeship@Michigan.gov) | No | N/A |
| IN | Apprenticeship Indiana (DWD/OWBLA) | https://www.in.gov/dwd/apprenticeship-indiana/home/ | Page 404'd at check time; no notice index found via search | No | N/A |
| WI | DWD Bureau of Apprenticeship Standards | https://acc.dwd.wisconsin.gov/apprenticeship/ | No public dated-notice list found; recruitment-source notification is a sponsor obligation, not a state-published feed | No | N/A |
| FL | Apprentice Florida / CareerSource network | https://apprenticeflorida.com/ | No central index; recruitment fragmented across ~24 regional CareerSource boards | No | N/A |
| MO | Apprenticeship Missouri (DHEWD) | https://dhewd.mo.gov/workforce-development/apprenticeship-mo | No dated-notice index found; program-directory style, not a recruitment feed | No | N/A |
| TN | ApprenticeshipTN | https://www.tn.gov/apprenticeshiptn/find-a-program.html | Searchable program table exists, but it's a program directory, not dated recruitment notices | No | Unconfirmed, likely static |
| NJ | NJDOL Office of Apprenticeship | https://nj.gov/labor/lwdhome/apprenticeship/apprenticeOnboarding1.shtml | No dated-notice index found; grant/funding notices exist but not apprentice recruitment notices | No | N/A |
| IA | Iowa Office of Apprenticeship / IowaWORKS | https://workforce.iowa.gov/apprenticeship | No dated-notice index; IowaWORKS.gov is a general job bank, not an apprenticeship-specific dated feed | No | N/A |
| WA | WA State Apprenticeship & Training Council (L&I) | https://www.lni.wa.gov/licensing-permits/apprenticeship/wsatc/ | Publishes council meeting agendas/minutes with dates, not recruitment notices | Dates are meeting dates, not application windows | N/A for recruitment purposes |

## Bottom line

Of the top 15 states, only **New York** publishes what you asked about: a central, browsable, dated apprenticeship recruitment-notice index (`dol.ny.gov/apprenticeship/apprenticeship-announcements`), static HTML, paginated, ~73 live notices, each with explicit opening/closing dates including years, filterable by region. This is exactly the source class that would have caught the LU 3 Westchester case and is a strong Pass-2-style crawl target on its own (single domain, ~8 pages of pagination, cheap).

Every other state in the top 15 either:
- has no centralized notice index (recruitment lives on individual JATC/local sites instead — which is already what Pass 2/3 harvest), or
- publishes a directory of registered *programs* (not time-bound recruitment notices), or
- the state page didn't resolve / 404'd at check time (OH, IN) and would need a follow-up look before ruling out.

**Recommendation for a future pass** (not building now, per your instruction): treat NY DOL as a 16th "local" target in the JATC-domain-style crawl — 8-page pagination, unrestricted crawl, `sitemap="skip"`, extract the same windows-array schema per notice, and match notices back to your 14 NY locals by sponsor name. This would be the direct fix for the Local 3 Westchester gap. OH and IN are worth a second look with fresh URLs since their agency pages returned DNS/404 errors that could be transient.
