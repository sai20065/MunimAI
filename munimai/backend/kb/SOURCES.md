# MUDRA KB sources (audit trail)

Fetched 2026-11-16 (UTC). Clause file: mudra.json

## Fetched and used
- https://www.mudra.org.in/offerings (2026-11-16) - Loan bands Shishu/Kishor/Tarun/Tarun Plus, purpose of loan, agri-allied exclusions, commercial-use-only vehicles, "collateral free" up to 20 lakh, no direct lending. Page footer shows copyright 2026.
- https://www.mudra.org.in/FAQ (2026-11-16) - Tarun Plus condition, eligible applicants, target segment, RBI collateral mandate, interest "deregulated", PAN/KYC, lender-governed terms.

Note: WebFetch got HTTP 403 from mudra.org.in; the pages were retrieved with curl (browser user-agent) and text-extracted. The rupee symbol did not survive extraction (rendered blank), so figures in the Shishu clause are written "Rs"; the numbers themselves are as on the page.

## Fetched, corroboration only (no clause taken)
- https://www.sidbi.in/blog/how-to-apply-for-pm-mudra-loan-online - Summarised via WebFetch; consistent with the four categories incl. Tarun Plus (10-20 lakh) and "collateral-free". Not quoted because the tool returned a summary, not raw text.

## Search results seen, not fetched
- WebSearch (official domains) surfaced SIDBI MSME report PDF, RAMP msme.gov.in PDFs, PMMY Bankers Kit (https://www.mudra.org.in/Home/PMMYBankersKit). Not fetched.

## Not attempted
- jansamarth.in, msme.gov.in, india.gov.in, rbi.org.in: not fetched; no RBI circular verified.

---
# Multi-scheme KB (added 2026-11-17)

Produced by `python -m backend.kb.fetch` then `python -m backend.kb.loader`. Clause text is verbatim page/PDF text,
split by heading (HTML) or by page and sentence groups (PDF); no model writes or paraphrases clauses. A re-fetch retires
older clauses of the same URL (`superseded_at`), never deletes them. One JSON file per scheme in this folder.

## Loaded (verified reachable with real content)
| scheme_code | clauses | sources |
|---|---|---|
| PMEGP | 46 | pmegp.msme.gov.in /Home/FAQ, /Home/TermsAndConditions, /Home/HomePage |
| CGTMSE | 168 | www.cgtmse.in home, /Home/VS/71 (FAQ), CGS-I Scheme Document PDF (updated 1 Apr 2025, first 30 pages) |
| PM_SVANIDHI | 7 | pmsvanidhi.mohua.gov.in |
| STANDUP_INDIA | 3 | www.standupmitra.in (success stories excluded) |
| PM_VISHWAKARMA | 12 | pmvishwakarma.gov.in |
| NSIC | 42 | www.nsic.co.in /Schemes/SinglePointRegistration, /RawMaterialAgainstBG, /MSMESaarthi |
| SIDBI | 21 | www.sidbi.in /en/working-capital, /en/machinery-loan, /en/business-loan |
| STARTUP_INDIA | 44 | startupindia.gov.in startup-scheme page; DPIIT recognition and tax-exemption page |
| SISFS | 41 | Startup India Seed Fund Scheme guidelines PDF (startupindia.gov.in) |
| STARTUP_PLAYBOOK | 91 | Startup Schemes Playbook, June 2026 PDF (startupindia.gov.in): Fund of Funds, central startup schemes |

## Gaps (not loaded, not guessed)
- **PMEGP subsidy-rate table (rural/urban %, own contribution):** not present in the reachable pmegp.msme.gov.in pages; it is on kviconline.gov.in, unreachable from here (connection fails from laptop and lab server).
- **CLCSS / SCLCSS / MSE-CDP and other MSME Ministry schemes:** msme.gov.in /schemes is JavaScript-rendered (0 clauses); dcmsme.gov.in, sclcss.msme.gov.in, my.msme.gov.in unreachable; scheme booklet PDFs on msme.gov.in return 404.
- **Udyam registration benefits:** udyamregistration.gov.in returns only a landing stub (1.7 KB, no scheme text).
- **Jan Samarth:** jansamarth.in is JavaScript-rendered (1 boilerplate line).
- **NIDHI (DST):** nidhi.dst.gov.in unreachable. Only what the Startup Playbook says about it is covered.
- **Karnataka startup/MSME schemes:** startup.karnataka.gov.in unreachable; ksfc.karnataka.gov.in pages are circular indexes (no rules text).
- **PM SVANidhi, Stand-Up India:** pages are thin (7 and 3 clauses); detailed guidelines PDFs not fetched.
- **kviconline.gov.in PMEGP guideline PDFs:** unreachable.

---
# Central gaps and state policies (added 2026-11-25)

Candidates were found by two research passes and then each was fetched with `python -m backend.kb.fetch --inspect`
and read for its **stated validity period** before loading. Every source is a `.gov.in` host.

## Loaded
| scheme_code | clauses | source | note |
|---|---|---|---|
| PMEGP | +33 | dkvib.delhi.gov.in, Revised PMEGP guidelines | Fills the old gap: subsidy rows (15/25/25/35 %), project-cost ceilings (Rs 50 lakh manufacturing, Rs 20 lakh service), upgradation limits. Delhi KVIB hosts the central guidelines text. |
| UDYAM | 2 | msme.gov.in, Annual Report 2025-26 (page 8 only) | The revised MSME classification in force from 1 Apr 2025 (micro 2.5 cr investment / 10 cr turnover, and so on). Only the classification clauses are kept (`FILTERS` in fetch.py); the rest of the report is history and statistics. |
| NIDHI | 94 | DST NIDHI-PRAYAS 2.0 guidelines, March 2026 (cdnbbsr.s3waas.gov.in) | Covers PRAYAS only, not NIDHI-SSS/EIR/TBI. |
| JAN_SAMARTH | 10 | PIB factsheet, June 2022 (static.pib.gov.in) | Descriptive and dated 2022; the number of linked schemes may have grown since. |
| UP_MSME_POLICY | 71 | invest.up.gov.in, UP MSME Promotion Policy 2022 | Effective five years from promulgation, so current. Capital and interest subsidy, stamp duty, EPF. |
| GUJARAT_IND_POLICY_2022 | 35 | static.investindia.gov.in, Gujarat Industrial Policy 2022 brochure | A summary brochure, not the Government Resolution. Validity period not stated in the extracted text (policy launched October 2022). |
| TAMILNADU_STARTUP_POLICY | 77 | startupindia.gov.in, Tamil Nadu Startup and Innovation Policy (successor to the 2018-23 policy) | Rule density is lower than the clause count suggests (much is vision text). |

## Found but deliberately NOT loaded (an expired or conflicting rule must never be cited as current)
- Karnataka Startup Policy (Startup India copy): it is the **2015-2020** policy.
- Maharashtra State Innovative Startup Policy 2018: period **2018 to 2023**.
- Tamil Nadu startup summary page: **2018-2023** policy.
- Maharashtra Package Scheme of Incentives 2019: ended **31 March 2024**.
- Karnataka New Industrial Policy 2020-25: expired in 2025.
- UP Startup Policy 2020 page: valid five years from notification, so likely ended; a successor is not yet notified.
- Udyam FAQ (MSME-DFO Gangtok, July 2024): carries the **old** classification limits (1/5, 10/50, 50/250 crore) that conflict with the 2025 limits above.
- PMEGP guideline PDFs (Odisha, Kerala): older ceilings (Rs 25 lakh / Rs 10 lakh) superseded by the Delhi KVIB text.
- Not .gov.in/.nic.in: ssipgujarat.in (student startup policy), investkarnataka.co.in (Karnataka Industrial Policy 2025-30 copy).
- UP Industrial Policy 2022 (large units) and Tamil Nadu Deep Tech Startup Policy: not MSME rules / mostly vision text.

## Karnataka and Telangana (added 2026-11-25)

| scheme_code | clauses | source | note |
|---|---|---|---|
| KARNATAKA_INDUSTRIAL_POLICY_2025_30 | 98 | investkarnataka.co.in, Operative Guidelines: Package of Incentives and Concessions under Industrial Policy 2025-30 (pages 95-125 of 186) | **Host is not .gov.in.** Allowed as a named exception (`config.py`, one line to revoke): the PDF's cover reads "Government of Karnataka, Department of Industries and Commerce ... approved vide Government Letter CI 123 SPI 2024, dated 10.04.2026", and the host is run by Karnataka Udyog Mitra, the state's investment facilitation agency. Only Section 11 (MSME incentives: capital subsidy for micro and small units, base subsidy for medium, stamp duty, registration, power) is loaded; pages 1-94 are large-industry rules and a table of contents. The policy period (five years from 08.02.2025) was reported by a research agent and is not in the loaded text. |
| TELANGANA_MSME_HANDBOOK_2024 | 277 | ipass.telangana.gov.in, Handbook of Government Schemes for MSMEs, 7 Oct 2024 (Government of Telangana, Industries) | A state **compilation** of state and central schemes, so it also fills part of the earlier CLCSS/SCLCSS, cluster-development and MSME-ministry gaps. Schemes where we hold a direct, newer source (PMEGP, SVANidhi, MUDRA, Stand-Up India, CGTMSE) and officials' contact pages are excluded (`EXCLUDES` in fetch.py). No policy period is stated; it is a dated 2024 document, so central-scheme figures in it may be older than the sources above. |

Found but not loaded (Telangana): T-PRIDE G.O. 78 (covers units starting 2015 to 31.03.2019, expired); the 2016/2017 Telangana Innovation Policy (no period stated, listed by Startup India as 2017-2022, so treated as expired); the 2021 grassroots-startup G.O. (garbled text, no period); the 2022 MSME compendium (superseded by the 2024 handbook); the food-processing society page (no period).
Karnataka, not loaded: Startup Policy 2022-27 and Elevate (startup.karnataka.gov.in does not resolve), CMEGP, KSFC schemes (reachable pages hold no rules), the State MSME Policy (only on non-official hosts), industries.karnataka.gov.in (fails TLS verification; not bypassed).

## Gaps still open (no reachable, current, official text)
- **Telangana MSME Policy 2024** (G.O.Ms.16 dated 18.09.2024, reported valid to 31.03.2029): the official PDF times out and the operational guidelines return HTTP 500. The handbook above carries only part of it. Retry later.
- **Karnataka:** Industrial Policy 2025-30, State MSME Policy, Elevate guidelines. **Maharashtra:** Industries, Investment and Services Policy 2025, MSME policy. **Tamil Nadu:** MSME Policy 2021 guidelines and TANSEED (kygcms.tn.gov.in, tansidco.tn.gov.in failed). **Gujarat:** the Government Resolution and i-Hub startup policy. **Uttar Pradesh:** a current startup policy. All other states and union territories were not attempted.
- CLCSS/SCLCSS, MSE-CDP, Champions and other MSME Ministry scheme guidelines (dcmsme.gov.in fails SSL verification; msme.gov.in scheme pages are JavaScript-rendered).
- NIDHI-SSS/EIR/TBI, an RBI priority-sector master direction, GST registration thresholds: not attempted.
- kviconline.gov.in (DNS failure from here).

## Allowlist additions (backend/config.py)
pmegp.msme.gov.in, pmsvanidhi.mohua.gov.in, pmvishwakarma.gov.in, www.standupmitra.in (SIDBI-run for Dept of Financial Services),
www.nsic.co.in / nsic.co.in (Govt of India PSU), www.sidbi.in / sidbi.in, www.startupindia.gov.in / startupindia.gov.in.
