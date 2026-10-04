# BUILD THE ACNABIN TENDER & OPPORTUNITY INTELLIGENCE AGENT (v3 — cloud, free tier)

## 0. HOW TO WORK

You are an expert Python engineer, web-automation engineer, procurement-intelligence analyst and AI-agent architect.

Build a working, production-oriented tender and opportunity monitoring system for **ACNABIN Chartered Accountants, Bangladesh**, hosted **entirely in the cloud on free tiers, with nothing running on a local PC**.

Working rules:

1. Build in the milestones in Section 31. After each milestone, run its tests, report results with evidence (commands run, counts, sample rows, workflow run links), and only then continue.
2. Deliver a **working vertical slice first** (a few sources → crawl → extract → classify → store → dashboard → alert) before widening coverage.
3. If an API key, network access or platform feature is unavailable in your environment, say so plainly, implement it anyway, test what you can, and mark the rest `NOT TESTED – REQUIRES <X>`. Never report something as working that you did not run.
4. Never put fabricated data into the production database. Synthetic fixtures are allowed only under `tests/fixtures/` and must be labelled as fixtures.
5. All business rules (banks, keywords, categories, scoring weights, schedules, thresholds, AI limits) live in `config/`, not in code.
6. Stay within free-tier limits (Section 3). Design for them from the start; do not discover them in production.

---

## 1. OBJECTIVE

Answer every day:

> "What new tender, RFP, RFQ, EOI, consultancy or professional-services opportunity has appeared that ACNABIN could realistically deliver, how urgent is it, and what evidence supports that?"

Precision/recall policy (different for different outputs):

* **Capture (database + review queue): recall-first.** Anything plausibly relevant is stored, even if uncertain.
* **Alerts: precision-first.** Only alert on items meeting the thresholds in Section 23.

---

## 2. HOSTING ARCHITECTURE

```text
 GitHub Actions (worker, Python, scheduled)          Cloudflare Pages (dashboard, static)
 ├─ crawl (httpx + Playwright)                        ├─ plain HTML/JS + supabase-js
 ├─ extract (PDF/DOCX/XLSX, Tesseract eng+ben)        ├─ Supabase Auth login (allow-listed emails)
 ├─ rules pre-filter                                  ├─ reads/edits via RLS-protected tables
 ├─ AI: Cloudflare Workers AI · Groq · Gemini         └─ client-side CSV/XLSX export
 ├─ scoring, dedupe, deadlines
 └─ alerts (Telegram, email)
            │                                                   │
            └───────────────►  SUPABASE  ◄──────────────────────┘
                        Postgres (+ pgvector) · Storage · Auth
```

* **GitHub Actions** is the only compute. It is stateless: every run reads and writes all state in Supabase.
* **Supabase** holds the database, document files, embeddings and dashboard logins. Do not use Supabase Edge Functions for crawling (CPU/time limits, no Python/Playwright/Tesseract).
* **Cloudflare Pages** serves a static dashboard. No server of our own.
* Local development: `run_monitor.py` must also run on a developer machine against the same Supabase project (or a local Supabase via CLI) for debugging.

---

## 3. FREE-TIER CONSTRAINTS (DESIGN FOR THESE)

Verify current limits in each provider's docs during setup and record them in `config/settings.yaml`. Known constraints to design around:

**Supabase free plan:** small database (~500 MB) and file storage (~1 GB) caps, limited egress, and projects pause after 7 days without activity. Therefore:
* store downloaded files only for records that become OPPORTUNITY or MARKET_INTELLIGENCE; for everything else keep hashes + metadata only;
* store extracted text only for relevant records, truncated to a configurable limit;
* retention job deletes files of IRRELEVANT/expired records after a configurable period;
* the hourly worker writes to Supabase every run, which keeps the project active; also add a weekly keep-alive workflow as a safeguard;
* the worker reports DB size and storage usage each run and warns at 70% / 90% of the cap.

**GitHub Actions:**
* Scheduled workflows use **UTC** and can start late (sometimes skipped) under load. Never rely on exact start times; each run must work from "last successful run" state, not from the clock.
* Free minutes are limited for private repositories. Target an average run under 4 minutes: cache pip and Playwright browsers, only run Playwright for sources flagged `requires_js`, use conditional GETs, process only changed content. Each run records its duration; the dashboard shows the projected monthly minutes.
* In public repositories, scheduled workflows are disabled after a period of repository inactivity; the keep-alive workflow must prevent this if the repo is public. Default: **private repository**.
* Runners are outside Bangladesh. Some Bangladeshi sites may be slow or block foreign IPs. Log these as `GEO_BLOCK_SUSPECTED` on the source-health page; never treat them as "no tenders". (A self-hosted runner can be added later without code changes.)

**AI providers (free tiers):** daily request/token limits apply. Usage is tracked in Supabase (`ai_usage` table) because runners keep no state between runs. When a limit is reached, items queue as `AI_REVIEW_PENDING` for the next run.

---

## 4. TWO PIPELINES — ROUTING IS DETERMINISTIC

Every candidate is routed by code, not by an LLM:

| Organization in fixed 30-bank list? | IFRS 9/ECL relevant? | Pipeline | record_type |
|---|---|---|---|
| Yes | Yes | `IFRS9_TARGET` (Pipeline A) | `OPPORTUNITY` or `MARKET_INTELLIGENCE` |
| No | Yes | `GENERAL_MARKET` (Pipeline B), category `IFRS9_ECL`, flag `outside_ifrs9_target=true` | `OPPORTUNITY` or `MARKET_INTELLIGENCE` |
| Either | No, but other ACNABIN service | `GENERAL_MARKET` | `OPPORTUNITY` or `MARKET_INTELLIGENCE` |
| Either | Not relevant | — | `IRRELEVANT` (stored minimally, hidden by default) |

Config switch `ifrs9_outside_target_mode` in `config/settings.yaml`:

* `general_market` (default) — non-target IFRS 9/ECL tenders appear in Pipeline B, so real opportunities (e.g. an NBFI ECL tender) are not lost.
* `intelligence_only` — stored as `MARKET_INTELLIGENCE`, never alert.

Pipeline A views and counts show **only** the 30 target banks, regardless of mode. Discovery never changes the 30-bank list.

---

## 5. PIPELINE A — 30 IFRS 9/ECL TARGET BANKS

Store in `config/ifrs9_banks.json`. Each entry: `id`, `canonical_name`, `aliases` (short names, abbreviations, former names, Bangla name), `official_domain`, `notes`.

Match organizations on canonical name **or** any alias (e.g. "RAKUB", "BKB", "BDBL", "MTB", "Premier Bank", "IBBL", Bangla names).

1. Agrani Bank PLC
2. Janata Bank PLC
3. Rupali Bank PLC
4. Mercantile Bank PLC
5. Midland Bank PLC
6. Citizens Bank PLC
7. Sonali Bank PLC
8. BASIC Bank PLC
9. Bangladesh Development Bank PLC
10. Sammilito Islami Bank PLC
11. Bangladesh Krishi Bank
12. Rajshahi Krishi Unnayan Bank
13. City Bank PLC
14. IFIC Bank PLC
15. Pubali Bank PLC
16. Dhaka Bank PLC
17. ONE Bank PLC
18. Mutual Trust Bank PLC
19. The Premier Bank PLC
20. Trust Bank PLC
21. Meghna Bank PLC
22. Modhumoti Bank PLC
23. Shimanto Bank PLC
24. Community Bank Bangladesh PLC
25. Bengal Commercial Bank PLC
26. Islami Bank Bangladesh PLC
27. ICB Islamic Bank PLC
28. Al-Arafah Islami Bank PLC
29. Commercial Bank of Ceylon PLC – Bangladesh
30. Woori Bank – Bangladesh

Implementation notes:

* Verify each official domain during setup and record `last_verified`. Do not guess; if unverifiable, mark `DOMAIN_REQUIRES_VERIFICATION`.
* Sammilito Islami Bank is a recently formed merged bank: add the predecessor banks' names as aliases.
* For foreign banks (29, 30), procurement may be on group/parent or Bangladesh-country pages; record whichever is official.
* A startup check asserts exactly 30 unique entries; the run fails loudly otherwise.

---

## 6. IFRS 9/ECL KEYWORDS — STRONG vs WEAK

Store in `config/keywords.json`.

**Strong terms** (one hit makes a candidate):

```text
IFRS 9, IFRS-9, IFRS9, International Financial Reporting Standard 9,
Expected Credit Loss, Expected Credit Losses, ECL model, ECL modelling, ECL modeling,
ECL software, ECL solution, ECL implementation, ECL validation,
IFRS 9 implementation, IFRS 9 consultant, IFRS 9 consultancy, IFRS 9 advisory,
IFRS 9 gap assessment, IFRS 9 readiness, IFRS 9 roadmap,
impairment model, impairment modelling, impairment modeling,
credit risk model, credit risk modelling, credit risk modeling,
12-month ECL, lifetime ECL, financial instrument impairment
```

**Weak terms** (count only if a strong term OR a procurement term from Section 10 is in the same document):

```text
ECL, PD, LGD, EAD, Probability of Default, Loss Given Default, Exposure at Default,
Stage 1, Stage 2, Stage 3, provisioning, loan loss provision, expected loss,
credit impairment, financial instruments
```

Reason: in Bangladeshi public documents "PD" usually means *Project Director*, "Stage 1" appears in many unrelated tenders, and "provisioning" is common in IT tenders.

Semantic matching (Section 16, embeddings) covers conceptually equivalent language with no keyword hit.

---

## 7. LANGUAGE — BANGLA IS MANDATORY

* Keyword lists include Bangla equivalents, e.g. দরপত্র, দরপত্র বিজ্ঞপ্তি, আগ্রহপত্র / আগ্রহ ব্যক্তকরণ (EOI), প্রস্তাব আহ্বান (RFP), কোটেশন, পরামর্শক / পরামর্শক প্রতিষ্ঠান, নিরীক্ষা, অভ্যন্তরীণ নিরীক্ষা, বহিঃনিরীক্ষা, সংশোধনী (corrigendum), সময় বৃদ্ধি (extension), বাতিল (cancellation), শেষ তারিখ (last date), স্মারক নং (memo no.). Verify and extend this list during the build.
* Normalize Bangla digits (০–৯) to ASCII before parsing dates and numbers.
* Parse Bangla month names; if only a Bangla-calendar date is given, store the raw text and mark `REQUIRES VERIFICATION`.
* OCR uses Tesseract with `eng` and `ben` (installed in the workflow via apt).
* All AI prompts state that input may be Bangla, English or mixed; outputs are always English.

---

## 8. PIPELINE B — SCOPE

**Primary (financial sector):** all scheduled banks (state-owned, private, Islamic, foreign, specialized, new, merged); NBFIs/finance/leasing companies; development finance institutions; merchant banks/asset managers; relevant microfinance institutions; life and general insurers.

**Regulators/government:** Bangladesh Bank, BSEC, IDRA, Financial Institutions Division, Ministry of Finance, Microcredit Regulatory Authority, and other public bodies' professional-services procurement.

**Public & donor procurement in Bangladesh (any sector), professional services only:** BPPA e-GP, World Bank, ADB, IFC, UNGM, UNDP, IOM, GIZ and other development partners/INGOs. Project, donor, NGO and SOE audits are core ACNABIN work and are in scope even when the client is not a financial institution — but only for services in Section 9, never goods or works.

Config switch `pipeline_b_sectors` lets the user narrow this.

---

## 9. ACNABIN SERVICE CATEGORIES (ENUM)

Use these exact codes everywhere (config, DB, AI schemas):

| Code | Covers | Base priority |
|---|---|---|
| `IFRS9_ECL` | IFRS 9 implementation/advisory/gap assessment, ECL modelling/validation/software, impairment & credit-risk modelling | VERY HIGH |
| `AUDIT_ASSURANCE` | statutory/external, internal, concurrent, branch, compliance, special, forensic, IT/IS, performance, donor/project audit, review engagements | HIGH |
| `RISK_CONTROL` | internal control framework/assessment/testing, ERM, operational/credit risk, governance, regulatory compliance, Basel advisory, AQR / banking diagnostics | HIGH (AQR & major banking diagnostics: VERY HIGH) |
| `ACCOUNTING_REPORTING` | IFRS/IAS advisory, accounting policies, financial reporting, FS review, finance-function advisory | HIGH |
| `PROCESS_ADVISORY` | business process review/re-engineering, SOPs, As-Is/To-Be, ERP controls, management consultancy | HIGH |
| `TAX_VAT` | tax/VAT advisory & compliance, transfer pricing | MEDIUM |
| `FINANCIAL_ADVISORY` | due diligence, valuation, feasibility, financial modelling, transaction advisory, project evaluation | MEDIUM |
| `TRAINING` | IFRS/audit/accounting/control/risk/compliance training | MEDIUM |
| `OTHER_PROFESSIONAL` | other services an accounting/advisory firm could realistically deliver (judgment, not keywords) | LOW |

Each category also has an English + Bangla keyword set and a 2–3 sentence description (used for embeddings) in `config/categories.json`.

Final priority comes from the score (Section 17), not free-text rules.

**Irrelevant procurement** (auto-reject unless a professional/advisory component is present): construction, civil works, renovation, furniture, stationery, vehicles, security, cleaning, catering, office supplies, generators, ACs, electrical equipment, printers, IT hardware, unrelated software, routine maintenance. If such a tender contains a meaningful advisory/audit component, send it to AI review instead.

**Fit type** (every opportunity): `DIRECT_FIT` | `PARTNERSHIP_REQUIRED` (e.g. ECL software, core banking or large IT transformation where ACNABIN would be adviser/consortium member/subcontractor) | `NOT_SUITABLE`.

---

## 10. OPPORTUNITY vs MARKET INTELLIGENCE

**OPPORTUNITY** — the organization is actually procuring: tender, e-tender, RFP, RFQ, EOI/REOI, consultant appointment, request for quotation, advisory/implementation/software procurement. Procurement language: invitation for tender, request for proposal, expression of interest, terms of reference, bid, quotation, submission deadline, bid security, tender schedule, plus the Bangla terms in Section 7.

**MARKET_INTELLIGENCE** — signals with no procurement: annual reports, financial statements, Bangladesh Bank circulars, accounting policies, news, speeches, investor presentations, strategy announcements, plans to implement IFRS 9/ECL or modernize risk/controls.

Examples:
* YES: "RFP for consultancy services for implementation of IFRS 9" · "Invitation for Internal Audit Services" · "EOI for Asset Quality Review Consultant" · "RFP for Risk Management Framework Consultant".
* NO (market intelligence): annual report mentioning IFRS 9 · Bangladesh Bank IFRS 9 circular · bank announces risk-system modernization.

Store both; only opportunities trigger opportunity alerts.

---

## 11. ORGANIZATION REGISTRY & DISCOVERY

`organizations` table fields:

```text
organization_id, canonical_name, aliases, organization_type, sector,
official_domain, procurement_url, tender_url, notice_url,
is_ifrs9_target (bool), source_status, last_verified, last_checked, notes
```

* Seed from Bangladesh Bank's published lists of scheduled banks and NBFIs, and IDRA's list of insurers (fetch current official lists; do not hand-type).
* Discovery runs **weekly** in its own workflow. New organizations get `PENDING_VERIFICATION` until their official domain is confirmed.
* Each new source gets its own baseline (Section 21).
* Discovery never touches `is_ifrs9_target`.

---

## 12. SOURCES & SOURCE TIERS

| Tier | Source | Use |
|---|---|---|
| 1 | Official bank/regulator/government website, BPPA e-GP, official donor procurement portal | Primary source of record |
| 2 | Recognized procurement platforms; **tender advertisements in national newspapers** (procurement rules require newspaper publication) | Valid source; link to Tier 1 when found |
| 3 | Tender aggregators | Discovery only |
| 4 | Search-engine results, social media, general news | Discovery / market intelligence only |

Always try to trace Tier 3/4 finds to Tier 1/2. Never present a Tier 3/4 page as the tender document when the official one exists. If no Tier 1/2 source is found, keep the opportunity with `source_verification = UNVERIFIED`.

Per organization, look for tender, procurement, notice, RFP/RFQ/EOI, consultancy, vendor, downloads and announcement pages. Investor-relations and report pages feed market intelligence only.

Per-source config in `config/sources.json` (synced to the `sources` table): `url, organization_id, tier, requires_js, verify_ssl, rate_limit_seconds, enabled`.

---

## 13. CRAWLING & SEARCH

**Crawling**
* Plain HTTP first (`httpx`) with conditional requests (ETag / If-Modified-Since stored in Supabase). Playwright only for sources with `requires_js: true` (set automatically when a static fetch returns an empty list but the rendered page does not).
* Descriptive User-Agent including `CRAWLER_CONTACT_EMAIL`.
* Respect robots.txt and per-domain rate limits (default ≥ 5 s per domain; crawl different domains concurrently with a bounded pool to keep runs short).
* Never bypass CAPTCHA, logins, paywalls or access controls. For login-gated portals collect only the public listing and link to it.
* Broken TLS is common on Bangladeshi sites. Do **not** disable verification globally; allow per-source `verify_ssl: false`, log every use, show it on source health.
* An inaccessible site is a source error, never evidence that no tender exists.
* Per-run time budget (`RUN_TIME_BUDGET_MINUTES`): if reached, stop gracefully, save progress, and continue remaining sources next run (round-robin by `last_checked`).

**Search-engine discovery**
* Use a configurable search **API** (e.g. Google Programmable Search, Brave Search API, SerpAPI). Never scrape search-result pages.
* Query patterns: `"<org or alias>" tender|RFP|RFQ|EOI|consultancy|IFRS 9|ECL|audit|internal audit|consultant`, sector-wide queries (e.g. "Bangladesh bank audit tender", "Bangladesh IFRS 9 tender"), plus Bangla variants.
* Cache results in Supabase; process only unseen URLs; respect `SEARCH_DAILY_QUERY_LIMIT`.

---

## 14. SCHEDULE (GitHub Actions)

Business schedule is **Asia/Dhaka (UTC+6)**: 00:00 and hourly 08:00–20:00. GitHub cron is UTC, so:

```yaml
# monitor.yml  — 00:00 Dhaka = 18:00 UTC; 08:00–20:00 Dhaka = 02:00–14:00 UTC
on:
  schedule:
    - cron: "7 18 * * *"
    - cron: "7 2-14 * * *"
  workflow_dispatch: {}
concurrency:
  group: monitor
  cancel-in-progress: false
jobs:
  run:
    timeout-minutes: 20
```

(Minute `7` avoids the top-of-hour congestion that delays scheduled runs.)

Not every task runs every time; the worker decides from Asia/Dhaka local time and from `last_run` records in Supabase:

| Task | Frequency |
|---|---|
| Tier 1/2 source checks (conditional GET, change detection) | every run |
| AI processing of new/changed candidates (within limits) | every run |
| Deadline checks & deadline alerts | every run |
| Search-engine discovery | first run at/after 08:00 and 14:00 Dhaka |
| Daily digest | first run at/after 08:00 Dhaka, covering previous 24 h, sent once per day |
| Organization discovery + market-intelligence crawl | separate `weekly.yml`, Sunday |
| Retention cleanup + usage report | `weekly.yml` |
| Keep-alive (Supabase ping; repo activity if public) | `keepalive.yml`, weekly |

Because runs can be late or skipped, "once per day" tasks are tracked by date in Supabase, not by exact hour. `concurrency` prevents overlapping runs. A failure on one source never aborts the run; a failed run is visible in the `runs` table and on the dashboard.

---

## 15. CHANGE DETECTION, AMENDMENTS, DUPLICATES

**Fingerprints** (stored in Supabase) per source page and document: `url, content_hash (normalized main text, not raw HTML), document_hash, title, publication_date, last_modified, etag, first_seen, last_seen`. Unchanged content is not re-processed.

**Material change** — diff and classify: deadline extension/revision, scope/TOR change, eligibility change, fee/bid-security change, submission-instruction change, pre-bid clarification, corrigendum/addendum, cancellation, re-tender. Cosmetic changes (layout, counters, render dates) are ignored.

**Linking amendments** — a corrigendum/addendum attaches to its parent by reference number, then by same organization + similar title. It creates an `opportunity_versions` row and an amendment alert, not a new opportunity. A re-tender with a new reference is a new opportunity linked to the old one.

**Duplicate merge** — merge when any of: same organization + same normalized reference number; same document hash; same organization + embedding similarity ≥ 0.90 (configurable) + same/overlapping deadline. **Never merge across organizations** — many banks issue near-identical "Internal Audit Services" tenders. Keep all source URLs in `opportunity_sources`; highest-tier source is primary.

---

## 16. EXTRACTION & AI PIPELINE

### 16.1 Extraction

Handle HTML, PDF, DOC/DOCX, XLS/XLSX. PDFs: download → hash → extract text with page numbers → detect image-only pages → Tesseract OCR (eng+ben) only on those pages. If OCR quality is low (confidence below threshold) and the item passes triage, send the PDF pages to Gemini (which reads scanned PDFs directly) instead.

Fields per opportunity (`NOT STATED` if absent, `REQUIRES VERIFICATION` if uncertain; never invent):

```text
organization, organization_type, title, reference_number, tender_type, category,
pipeline, priority, score, fit_type, publication_date, submission_deadline,
opening_datetime, prebid_meeting, clarification_deadline, scope_of_work,
eligibility, minimum_experience, required_certifications, required_team,
required_documents, bid_security, tender_fee, contract_period, estimated_value,
submission_method, submission_address, contact_person, contact_email, contact_phone,
source_url, document_url, evidence (document, page, section, quoted text),
ai_confidence, first_seen, last_checked
```

Dates: store `timestamptz` (UTC) plus the raw string as found; display in Asia/Dhaka. Bangladeshi documents use DD/MM/YYYY — never parse as MM/DD. Ambiguous → raw text + `REQUIRES VERIFICATION`.

**Audit eligibility flags** — extract, never decide: FRC enlistment, Bangladesh Bank audit panel enlistment, other panel membership, years of experience, partner qualifications, firm turnover, certifications, similar-assignment counts.

### 16.2 AI modes

`AI_MODE` in settings/secrets:

* `off` — rules only (16.4 rule-based fallbacks). Everything uncertain → `REVIEW_REQUIRED`.
* `triage_only` — rules + embeddings + Groq triage; extraction by regex rules.
* `full` (default) — all stages below.

The system must be fully functional in `off` mode; AI improves quality but is never required for the pipeline to run.

### 16.3 Stages (full mode)

| Stage | Provider | Input | Output |
|---|---|---|---|
| 0. Rules pre-filter | code | full text | candidate or reject (org match, procurement language, strong/weak keywords, irrelevant list, date detection) |
| 1. Semantic match | **Cloudflare Workers AI** — multilingual embedding model (`CLOUDFLARE_EMBED_MODEL`) | title + first ~2,000 chars | similarity to each category description; vectors stored in Supabase `pgvector` for dedupe |
| 2. Triage | **Groq** (`GROQ_TRIAGE_MODEL`) | title, source, first page, keyword/embedding signals | opportunity vs intelligence vs irrelevant, category, keep/drop, confidence |
| 3. Full extraction | **Gemini** (`GEMINI_MODEL`) — structured output | relevant pages only (see context limits) or PDF directly for scanned docs | full schema (16.5) |
| 4. Second-opinion review | **Groq**, different model family from stage 2 (`GROQ_REVIEW_MODEL`) | title, extracted text, Gemini result, evidence, eligibility text | review schema (16.6) |

Stage-1 semantic catch: documents with procurement language but **no keyword hit** go to triage if their best category similarity ≥ `SEMANTIC_THRESHOLD`.

Stage-4 review runs only when at least one is true: category `IFRS9_ECL`; priority VERY HIGH; Gemini confidence LOW; `is_opportunity = UNCERTAIN`; material amendment to a HIGH+ opportunity; eligibility text present on a HIGH+ opportunity.

**Fallback chain** (per item): if Gemini fails or is at its limit → Groq does extraction with the same schema; if Groq fails → Gemini does triage/review; if both unavailable → rule-based fallback and `AI_REVIEW_PENDING` for re-processing next run. If Cloudflare embeddings fail → skip semantic catch for that run and log it. No stage may block the run.

**Context limits:** never send whole long documents. Send title, source, first 2 pages, all pages with keyword/procurement hits, and eligibility/qualification/ToR sections, capped at `AI_MAX_INPUT_CHARS`, page numbers preserved.

**Cost/limit controls** (secrets/config): `GROQ_DAILY_CALL_LIMIT`, `GEMINI_DAILY_CALL_LIMIT`, `CLOUDFLARE_DAILY_CALL_LIMIT`, tracked in `ai_usage` (provider, model, date, calls, tokens). Never hard-code model names.

**Data policy:** free AI tiers may use inputs to improve their models. Send only public tender/notice content. Never send internal ACNABIN documents, client data or user notes to any AI provider.

### 16.4 Rule-based fallbacks (used in `off` mode and on AI failure)

* Opportunity = procurement language + (deadline or submission instruction); otherwise market intelligence if relevant terms present.
* Category = highest weighted keyword-set score; tie → `REVIEW_REQUIRED`.
* Fit type = software/system/license/implementation-partner terms → `PARTNERSHIP_REQUIRED`.
* Fields by regex: reference ("Ref", "Memo No", "স্মারক নং", "Tender No"), dates near deadline words (EN + BN), amounts after Tk/BDT/টাকা, emails, phones, eligibility sections by heading.
* Confidence: strong keyword + clear title + parsed deadline = HIGH; reduce for each missing signal.
* `relevance_reason` templated: "Matched: <terms>, deadline <date>, p.<n>".

### 16.5 Extraction schema (Gemini / Groq fallback)

Use each API's structured-output / JSON-schema mode:

```json
{
  "is_opportunity": "YES | NO | UNCERTAIN",
  "record_type": "OPPORTUNITY | MARKET_INTELLIGENCE | IRRELEVANT",
  "ifrs9_ecl_relevant": true,
  "category": "IFRS9_ECL | AUDIT_ASSURANCE | RISK_CONTROL | ACCOUNTING_REPORTING | PROCESS_ADVISORY | TAX_VAT | FINANCIAL_ADVISORY | TRAINING | OTHER_PROFESSIONAL | NONE",
  "acnabin_relevant": "YES | POSSIBLY | NO",
  "fit_type": "DIRECT_FIT | PARTNERSHIP_REQUIRED | NOT_SUITABLE",
  "organization": "",
  "title": "",
  "reference": "",
  "publication_date_raw": "",
  "deadline_raw": "",
  "scope_summary": "",
  "potential_acnabin_service": "",
  "relevance_reason": "",
  "eligibility_summary": "",
  "eligibility_concerns": [""],
  "evidence": [{ "page": 1, "text": "" }],
  "confidence": "HIGH | MEDIUM | LOW"
}
```

AI does **not** assign pipeline, score or priority — code does (Sections 4 and 17).

### 16.6 Review schema (stage 4)

`is_genuine_procurement`, `acnabin_relevant`, `category_correct` (+ suggested category), `evidence_sufficient`, `eligibility_concerns`, `suspect_fields` (field names likely wrong), `review_summary` (≤ 3 sentences). Store `review_result` and `review_summary` only; never request or store hidden reasoning. If the reviewer disagrees with extraction, set `review_status = REVIEW_REQUIRED` for a human; do not silently overwrite.

### 16.7 Validation of all AI output

Valid JSON against schema; dates parse; every evidence quote must appear in the source text (fuzzy match) or it is dropped; organization matches the registry or is flagged; URLs always come from the crawler, never from a model. Invalid JSON → one repair attempt → one retry → `REVIEW_REQUIRED`. Retries use exponential backoff and respect HTTP 429 `Retry-After`.

---

## 17. SCORING & PRIORITY (DETERMINISTIC)

`score` (0–100) from weights in `config/scoring.yaml`, e.g.:

* category base: IFRS9_ECL 60, AUDIT_ASSURANCE / RISK_CONTROL / ACCOUNTING_REPORTING 50, PROCESS_ADVISORY 45, TAX_VAT / FINANCIAL_ADVISORY 40, TRAINING 35, OTHER_PROFESSIONAL 25
* is_opportunity = YES: +15
* organization is a bank/regulator/major FI: +10
* fit DIRECT_FIT: +10; PARTNERSHIP_REQUIRED: +3
* source tier 1/2: +5
* confidence LOW: −15; MEDIUM: −5
* AQR / major banking diagnostic: +10
* clamp 0–100

| Score | Priority |
|---|---|
| 85–100 | VERY HIGH |
| 70–84 | HIGH |
| 55–69 | MEDIUM |
| 40–54 | LOW |
| < 40 | IGNORE |

Calibrate weights in testing so Section 10 YES examples land HIGH or above and NO examples are not opportunities. Store `score`, `score_breakdown`, `reasoning_summary`.

---

## 18. STATUS MODEL — SEPARATE FIELDS

* `record_type`: OPPORTUNITY | MARKET_INTELLIGENCE | IRRELEVANT
* `pipeline`: IFRS9_TARGET | GENERAL_MARKET
* `outside_ifrs9_target`: bool
* `lifecycle_status`: NEW | ACTIVE | DEADLINE_APPROACHING | SUBMISSION_CLOSED | EXTENDED | CANCELLED | RETENDERED | AWARDED
* `review_status`: AI_REVIEW_PENDING | REVIEW_REQUIRED | VERIFIED | SHORTLISTED | NOT_PURSUING
* `is_baseline`: bool
* `fit_type`: DIRECT_FIT | PARTNERSHIP_REQUIRED | NOT_SUITABLE
* `source_verification`: VERIFIED | UNVERIFIED
* Sources table: OK | ERROR | GEO_BLOCK_SUSPECTED | SOURCE_REQUIRES_REVIEW | PENDING_VERIFICATION

Implement enums as Postgres enum types or check constraints.

---

## 19. HUMAN-IN-THE-LOOP

* Never state "ACNABIN is eligible". Use: "Potentially eligible — verify tender eligibility and ACNABIN credentials."
* Dashboard users can edit priority, category, relevance, review_status, fit_type and notes.
* Every human edit is written to `manual_overrides` (field, value, user, timestamp) and the field is **locked**: the worker never overwrites it; if the source later changes, it flags "source changed since your edit".
* Notes: free text plus quick tags (Contacted bank, Partner informed, Proposal team reviewing, Eligibility confirmed, Need consortium, Need technical partner, Deadline extended, Not pursuing, Potential client). Notes are never sent to AI providers.

---

## 20. DEADLINES

For every `record_type = OPPORTUNITY`, compute days remaining in Asia/Dhaka each run and update lifecycle_status.

Deadline alerts (7, 3, 1 day before) only for priority HIGH+ **or** review_status SHORTLISTED, never for NOT_PURSUING. Because runs can be late or skipped, an alert fires on the **first run at or after** each threshold, once per deadline value (tracked in `alerts`). A changed deadline resets thresholds and sends an amendment alert.

---

## 21. BASELINE

Per source, on its first successful crawl (including sources added later):

* Deadline passed, or no deadline and older than 30 days → `is_baseline = true`, no alert.
* Deadline still in the future → stored normally, shown on the dashboard, and included once in an **"Open opportunities found at setup"** digest — no individual alerts.

After baseline, only new items and material changes alert.

---

## 22. DATABASE (SUPABASE POSTGRES)

* Schema managed as SQL migrations in `supabase/migrations/` (Supabase CLI). No manual dashboard edits to schema.
* Enable `pgvector` for embeddings.
* Tables: `organizations, sources, source_checks, documents, document_versions, opportunities, opportunity_versions, opportunity_sources, evidence, alerts, market_intelligence, ai_reviews, ai_usage, manual_overrides, notes, runs, search_cache, app_users`.
* `opportunities` minimum fields: all fields from Sections 16.1 and 18, plus `organization_id, content_hash, document_hash, extraction_result (jsonb), review_result (jsonb), score_breakdown (jsonb), embedding (vector), first_seen, last_seen`.
* Indexes on reference_number, organization_id, deadline, priority, review_status, content_hash, document_hash.
* Files in Supabase Storage bucket `documents` (private), path `<organization_id>/<document_hash>.<ext>`. Dashboard gets short-lived signed URLs.
* Database views for the dashboard: `v_today_priority`, `v_ifrs9_target`, `v_general_market`, `v_source_health`, `v_run_summary`, `v_kpis`.

**Security (RLS):**
* RLS enabled on every table.
* Worker uses the **service-role key**, stored only in GitHub Actions secrets.
* Dashboard uses the **anon key** + Supabase Auth. Only emails in `app_users` (allow-list) can read; they can update only the editable fields in Section 19 and insert notes/overrides. Sign-ups disabled; users invited.
* The service-role key must never appear in the dashboard code or repository.

---

## 23. ALERTS & DIGEST

Modular channels in `app/alerts/` with a common interface:

1. **Telegram** (primary — simple, free, reliable).
2. **Email** via SMTP (port 587, e.g. Gmail app password) or an HTTP email API (configurable).

Immediate alerts only for:
* new OPPORTUNITY with priority VERY HIGH or HIGH;
* material amendment (deadline, scope, eligibility, cancellation, re-tender) to an opportunity that is HIGH+ or SHORTLISTED;
* deadline thresholds per Section 20.

Never send the same alert twice (dedupe key: opportunity_id + alert_type + deadline/version, unique constraint in `alerts`).

Alert format:

```text
NEW ACNABIN OPPORTUNITY  [VERY HIGH | HIGH]
Organization:     
Pipeline:         IFRS 9 TARGET | GENERAL MARKET (outside IFRS 9 target, if applicable)
Tender:           
Reference:        
Category:         
Fit:              DIRECT_FIT | PARTNERSHIP_REQUIRED
Why relevant:     
Potential service:
Published:        
Deadline:         (N days left)
Eligibility:      (summary + flags; "Potentially eligible — verify")
Source:           (official URL, tier)
Tender document:  
Evidence:         (document, page, short quote)
Confidence:       
Dashboard:        (Cloudflare Pages link to the opportunity)
```

**Daily digest** (once per day, first run at/after 08:00 Dhaka, previous 24 h; concise): VERY HIGH · HIGH · MEDIUM · Amendments · Deadlines within 7 days · Market intelligence · Source errors · Free-tier usage warnings. Skip empty sections; send "No new items" if all empty.

---

## 24. DASHBOARD (CLOUDFLARE PAGES)

Static site in `dashboard/`: plain HTML + vanilla JS + `supabase-js` (from an allowed CDN), no framework build step. Deployed to Cloudflare Pages from the repo (Pages Git integration or a deploy workflow). Config (`SUPABASE_URL`, anon key) injected at deploy time.

Login with Supabase Auth (magic link or email/password, allow-listed users only).

Pages:
* **Home** — "Today's priority opportunities" (priority → days to deadline → score → confidence → estimated value); KPIs: organizations monitored, 30 IFRS 9 target banks, general-market organizations, sources, new today, VERY HIGH, HIGH, deadlines ≤ 7 days, source errors, pending AI reviews, last run time/status.
* **IFRS 9** — only the 30 target banks: IFRS 9/ECL opportunities, IFRS 9 market intelligence, per-bank history.
* **General market** — all opportunities, all categories.
* **Opportunity detail** — all fields, evidence with signed links to the document page, AI assessments (extraction + review), score breakdown, change history, sources, notes, editable fields.
* **Market intelligence.**
* **Source health** — last success/failure, consecutive failures, HTTP status, error, `verify_ssl` overrides, GEO_BLOCK_SUSPECTED. 3 consecutive failures → `SOURCE_REQUIRES_REVIEW`; keep retrying.
* **Operations** — recent runs (duration, counts, errors), projected monthly Actions minutes, DB/storage usage vs cap, AI usage vs daily limits.

Filters: pipeline, organization, organization type, category, priority, date, deadline range, lifecycle_status, review_status, confidence, new/existing, fit_type, outside_ifrs9_target.

Export (current filter), generated client-side: **Excel** (SheetJS) and **CSV**, columns: Organization, Organization Type, Pipeline, Tender Title, Reference, Category, Priority, Score, Fit Type, Publication Date, Deadline, Scope, Potential ACNABIN Service, Eligibility, Source URL, Tender Document URL, Evidence, Page, Confidence, Lifecycle Status, Review Status, First Seen, Last Checked.

Must work on mobile width.

---

## 25. LOGGING

* Structured JSON logs to stdout (captured by GitHub Actions run logs).
* Per-run summary row in `runs`: start/end, duration, sources checked/failed, documents new/changed, candidates, AI calls per provider, alerts sent, errors.
* Per-source result rows in `source_checks`.
* Errors include stack traces in Actions logs; a short message in Supabase.
* A failed workflow run (non-zero exit) only for fatal problems (config invalid, Supabase unreachable); per-source errors do not fail the run.

---

## 26. SECRETS & CONFIG

GitHub Actions secrets (worker). `.env` only for local development (in `.gitignore`; `.env.example` committed):

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
AI_MODE=full                 # off | triage_only | full
GROQ_API_KEY=
GROQ_TRIAGE_MODEL=
GROQ_REVIEW_MODEL=
GROQ_DAILY_CALL_LIMIT=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_EMBED_MODEL=
CLOUDFLARE_DAILY_CALL_LIMIT=
GEMINI_API_KEY=
GEMINI_MODEL=
GEMINI_DAILY_CALL_LIMIT=
AI_MAX_INPUT_CHARS=
SEMANTIC_THRESHOLD=
SEARCH_PROVIDER=
SEARCH_API_KEY=
SEARCH_ENGINE_ID=
SEARCH_DAILY_QUERY_LIMIT=
CRAWLER_CONTACT_EMAIL=
RUN_TIME_BUDGET_MINUTES=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
ALERT_EMAIL_TO=
DASHBOARD_BASE_URL=
```

Dashboard (Cloudflare Pages environment variables): `SUPABASE_URL`, `SUPABASE_ANON_KEY` only.

Never commit secrets. Add a CI check (e.g. a secret scanner step) that fails if a key pattern appears in the repo.

---

## 27. PROJECT STRUCTURE

```text
acnabin-tender-monitor/
├── .github/workflows/
│   ├── monitor.yml        # hourly schedule (Section 14)
│   ├── weekly.yml         # discovery, market intelligence, retention, usage report
│   ├── keepalive.yml
│   ├── tests.yml          # on push/PR
│   └── deploy-dashboard.yml  # if not using Pages Git integration
├── app/
│   ├── crawler/  discovery/  parsers/  extraction/  ocr/
│   ├── classification/  ai/ (cloudflare.py, groq.py, gemini.py, router.py)
│   ├── scoring/  db/  alerts/  utils/
├── config/
│   ├── settings.yaml          # modes, thresholds, schedule, rate limits, free-tier caps
│   ├── ifrs9_banks.json       # exactly 30, with aliases
│   ├── organizations.json     # seed registry
│   ├── sources.json
│   ├── keywords.json          # strong/weak/procurement/irrelevant, EN + BN
│   ├── categories.json        # codes, keywords, embedding descriptions
│   └── scoring.yaml
├── supabase/
│   ├── migrations/            # schema, enums, views, RLS policies
│   └── seed.sql
├── dashboard/                 # static site for Cloudflare Pages
│   ├── index.html  ifrs9.html  market.html  opportunity.html
│   ├── intelligence.html  sources.html  operations.html
│   └── js/  css/
├── tests/  fixtures/
├── .env.example  .gitignore  requirements.txt
├── run_monitor.py             # one run (used by Actions and locally)
├── run_weekly.py
└── README.md
```

Python 3.11+. Dependencies pinned. Workflow installs Tesseract (`tesseract-ocr`, `tesseract-ocr-ben`) and Playwright Chromium with caching.

---

## 28. ERROR HANDLING

Handle and log without stopping the run: HTTP 403/404/429 (respect Retry-After)/5xx, timeouts, DNS failures, TLS errors, suspected geo-blocks, malformed/encrypted PDFs, OCR failure, Playwright render failure, AI API failure or limit, malformed AI output, Supabase transient errors (retry with backoff), storage cap reached (skip file storage, keep metadata, warn), run time budget reached (save progress, continue next run).

---

## 29. TESTING

Tests run in `tests.yml` on every push. Fixtures in `tests/fixtures/` (real public documents saved locally where allowed, otherwise clearly synthetic). AI calls are mocked in unit tests; a separate, manually triggered integration test calls the real providers.

* **Web:** static page, JS-rendered list, PDF-link page, paginated list, broken-TLS site, timeout/geo-block simulation.
* **Documents:** text PDF, scanned PDF (English and Bangla), multi-page PDF, malformed PDF, DOCX, XLSX.
* **Language:** Bangla notice with Bangla digits/dates; bilingual notice.
* **Classification:** IFRS 9 tender at target bank; IFRS 9 tender at non-target NBFI (routing per mode); audit tender; internal audit tender; construction tender (rejected); construction tender with audit component (sent to AI); news article; annual report; Bangladesh Bank circular; Bangladesh Bank procurement; donor project audit; "PD = Project Director" document (must not hit IFRS 9).
* **AI modes:** same fixtures in `off`, `triage_only`, `full`; fallback when each provider fails; daily limit reached → `AI_REVIEW_PENDING`; evidence quote not in source → dropped; invalid JSON handling.
* **Change:** new tender, unchanged page, cosmetic-only change, amended tender, extended deadline, replaced PDF, cancellation.
* **Duplicates:** official site + aggregator; same PDF at two URLs; near-identical tenders from two banks (must NOT merge).
* **Alerts:** no duplicates across runs; deadline thresholds fire once even when a run is skipped; manual override not overwritten.
* **Scheduling:** digest sent once per day when the 08:00 run is late or skipped; overlapping runs prevented; run time budget resumes correctly.
* **Security:** anon key cannot read without login; non-allow-listed user denied; dashboard user cannot edit locked/non-editable fields; no service-role key in dashboard bundle.

---

## 30. FIRST REAL RUN & REPORT

After tests pass, trigger `monitor.yml` via `workflow_dispatch` against real public sources (rate-limited), then report actual numbers:

1. Target banks loaded (must be 30); domains verified / unverified.
2. General-market organizations seeded and from which official lists.
3. Sources by tier; failing sources and why (incl. suspected geo-blocks).
4. Documents fetched; candidates after pre-filter; semantic-catch additions.
5. Opportunities by category/priority; IFRS 9 opportunities; market-intelligence items; rejected count with 5 example rejections.
6. 3 sample opportunities with evidence and source links.
7. AI calls per provider vs limits; fallbacks used.
8. Run duration and projected monthly Actions minutes; DB and storage usage.
9. Dashboard live on Cloudflare Pages with login working; Excel/CSV export tested.
10. Telegram/email alert received (test alert if no real opportunity).
11. Known gaps and sources needing manual attention.

If zero live opportunities exist today, say so — do not invent any.

---

## 31. MILESTONES

1. **Foundation** — repo, config, Supabase project + migrations + RLS, 30-bank registry with aliases, logging, `tests.yml`.
2. **Vertical slice** — 5 real sources (at least one Bangla, one PDF-based) end-to-end: crawl → extract → rules → Groq triage → Gemini extraction → score → Supabase → minimal dashboard on Cloudflare Pages → Telegram alert, all running from `monitor.yml`.
3. **Change detection, amendments, duplicates** (incl. embeddings + pgvector).
4. **Full extraction** — OCR (eng+ben), Gemini PDF fallback, DOCX/XLSX, date normalization.
5. **AI routing** — `AI_MODE`, review stage, fallback chain, validation, usage limits.
6. **Source & organization discovery** — registry seeding, search API, tiering, `weekly.yml`.
7. **Deadlines, digest, email channel.**
8. **Full dashboard** — all pages, filters, overrides, exports, source health, operations.
9. **Free-tier hardening** — retention, usage monitoring, keep-alive, run time budget, minutes projection.
10. **Full test suite + first real run report (Section 30) + README.**

---

## 32. README

Cover: architecture overview; creating the Supabase project (enable pgvector, run migrations, create storage bucket, disable sign-ups, invite users); creating the GitHub repo and adding Actions secrets; getting Groq, Cloudflare Workers AI and Gemini keys and choosing models; choosing a search API; connecting Cloudflare Pages and setting its env vars; first run and baseline; running locally for debugging; changing `AI_MODE`; adding notification channels; adding/removing organizations and sources; editing the 30-bank list (exact-30 check); editing keywords/categories/scoring; per-source `verify_ssl` and `requires_js`; free-tier limits and what to do when approaching them (including moving to a self-hosted runner or paid tier); troubleshooting (blocked/geo-blocked sites, TLS errors, OCR, AI limits, late scheduled runs, paused Supabase project, RLS errors).

---

## 33. DONE MEANS

**Pipeline A:** exactly 30 target banks with aliases · IFRS 9/ECL detection in English and Bangla · strong/weak keyword logic prevents acronym false positives · market intelligence separate.

**Pipeline B:** registry seeded from official lists · weekly discovery adds organizations without touching the 30 · ACNABIN-relevant tenders found, irrelevant procurement filtered · non-target IFRS 9 routing follows the configured mode.

**Intelligence:** rules → embeddings → Groq triage → Gemini extraction → Groq review, each within free limits · full pipeline works in `AI_MODE=off` · fallback chain never blocks a run · evidence verified against source text · deterministic score and priority · eligibility flags surfaced, never decided.

**Monitoring:** new page/document detection · amendment linking · duplicate merge (never across organizations) · deadline alerts once per threshold even with late/skipped runs · per-source baseline.

**Operations:** runs entirely on GitHub Actions + Supabase + Cloudflare Pages, nothing local · Supabase persistence with RLS · login-protected dashboard with overrides · Excel/CSV export · Telegram + email alerts and daily digest · structured logs and run records · free-tier usage monitored · graceful error handling.

The system must be **persistent, evidence-based, deduplicated, source-verifiable and human-in-the-loop** — not "search Google for IFRS 9 every hour."
