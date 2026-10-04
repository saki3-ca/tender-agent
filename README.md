# ACNABIN Tender & Opportunity Intelligence Agent (v3 — Cloud, Free Tier)

A fully automated, production-grade tender, RFP, and procurement intelligence system developed for **ACNABIN Chartered Accountants, Bangladesh**.

Hosted **entirely in the cloud on free-tier services** with zero dependencies on local workstations:
* **Compute:** GitHub Actions (scheduled worker running in Asia/Dhaka business hours).
* **Database & Persistence:** Supabase (Postgres with `pgvector`, Row Level Security, Storage, Auth).
* **Dashboard:** Cloudflare Pages (responsive static single-page application with client-side Excel/CSV export).
* **AI Intelligence Tier:** Multi-stage pipeline leveraging Cloudflare Workers AI, Groq, and Google Gemini with deterministic rule-based fallbacks.
* **Alerts:** Immediate push notifications to Telegram and email.

---

## 1. System Architecture

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

### Two Deterministic Pipelines
All routing decisions are performed by deterministic code, **never** delegated to an LLM:

| Organization in fixed 30-bank list? | IFRS 9 / ECL relevant? | Pipeline | `record_type` |
|---|---|---|---|
| **Yes** | **Yes** | `IFRS9_TARGET` (Pipeline A) | `OPPORTUNITY` or `MARKET_INTELLIGENCE` |
| **No** | **Yes** | `GENERAL_MARKET` (Pipeline B), category `IFRS9_ECL`, `outside_ifrs9_target=true` | `OPPORTUNITY` or `MARKET_INTELLIGENCE` |
| **Either** | **No, but other ACNABIN service** | `GENERAL_MARKET` (Pipeline B) | `OPPORTUNITY` or `MARKET_INTELLIGENCE` |
| **Either** | **Not relevant** | — | `IRRELEVANT` (auto-rejected) |

---

## 2. Directory Structure

```text
acnabin-tender-monitor/
├── .github/workflows/
│   ├── monitor.yml            # Hourly schedule (00:00 & 08:00–20:00 Asia/Dhaka)
│   ├── weekly.yml             # Discovery, market intelligence, retention
│   ├── keepalive.yml          # Supabase ping to prevent 7-day pause
│   ├── tests.yml              # CI automated test runner
│   └── deploy-dashboard.yml   # Cloudflare Pages deployment
├── app/
│   ├── crawler/               # Async httpx + Playwright web crawler
│   ├── parsers/               # HTML, PDF, DOCX, XLSX, and Bangla date parsers
│   ├── classification/        # Deterministic rules pre-filter and deduplication engine
│   ├── ai/                    # Cloudflare, Groq, Gemini clients & multi-stage router
│   ├── scoring/               # Deterministic scoring engine (0-100) and priority bands
│   ├── alerts/                # Telegram and SMTP email alerting modules
│   ├── db/                    # Supabase PostgREST client and in-memory mock adapter
│   └── utils/                 # Structured JSON logging & configuration validator
├── config/
│   ├── settings.yaml          # Free-tier caps, rate limits, timeouts, modes
│   ├── ifrs9_banks.json       # Exactly 30 fixed target banks with aliases
│   ├── organizations.json     # Seed registry of banks, NBFIs, regulators
│   ├── sources.json           # Per-source URLs, tiers, SSL and JS configurations
│   ├── keywords.json          # Strong/weak IFRS 9, Bangla terms, procurement language
│   ├── categories.json        # 9 official ACNABIN service categories
│   └── scoring.yaml           # Deterministic weights and priority thresholds
├── supabase/
│   ├── migrations/            # 20261001000001_initial_schema.sql, 20261001000002_views_and_rls.sql
│   └── seed.sql               # Seed data for 30 target banks and initial users
├── dashboard/                 # Static dashboard ready for Cloudflare Pages
│   ├── index.html             # Today's Priority Opportunities & KPIs
│   ├── ifrs9.html             # Pipeline A (30 target banks only)
│   ├── market.html            # Pipeline B (General market opportunities)
│   ├── opportunity.html       # Detailed dossier, verified evidence, partner locks
│   ├── intelligence.html      # Regulatory circulars & early market signals
│   ├── sources.html           # Real-time source health, SSL and geo-block telemetry
│   ├── operations.html        # GitHub Actions duration, DB storage & AI quotas
│   ├── css/style.css          # Glassmorphism dark-mode design system
│   └── js/                    # config.js and app.js with Excel (SheetJS) export
├── tests/                     # Comprehensive test suite (23 unit & integration tests)
│   └── fixtures/              # Synthetic test fixtures
├── run_monitor.py             # Main entry point for hourly runs and local debugging
├── run_weekly.py              # Weekly maintenance, discovery, and cleanup runner
├── requirements.txt           # Pinned Python dependencies
└── .env.example               # Template environment configuration
```

---

## 3. Step-by-Step Setup Guide

### 3.1 Setting Up Supabase (Free Tier)
1. Sign up for a free account at [supabase.com](https://supabase.com) and create a new project.
2. In the Supabase Dashboard, navigate to **Project Settings -> Database** and copy the **Project URL** and **Service Role Key** (under API Keys).
3. Open the **SQL Editor** in Supabase and execute the migration files in order:
   - Run `supabase/migrations/20261001000001_initial_schema.sql` (Creates enums, tables, indexes, pgvector).
   - Run `supabase/migrations/20261001000002_views_and_rls.sql` (Creates dashboard views, helper functions, and RLS policies).
   - Run `supabase/seed.sql` (Seeds default allow-listed users and 30 target banks).
4. Navigate to **Storage** and ensure a bucket named `documents` exists (set to private).
5. In **Authentication -> Configuration**, disable public sign-ups so only invited partner emails can access. Add partner emails to the `app_users` table.

### 3.2 Setting Up GitHub Repository & Secrets
1. Push this repository to your GitHub account (private repository recommended).
2. Go to **Settings -> Secrets and variables -> Actions** and add the following repository secrets:

```text
SUPABASE_URL               = https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY  = your-supabase-service-role-key
SUPABASE_ANON_KEY          = your-supabase-anon-key

# AI Modes & Providers (Free tier keys)
AI_MODE                    = full  # full | triage_only | off
GROQ_API_KEY               = gsk_...
GROQ_TRIAGE_MODEL          = llama-3.3-70b-versatile
GROQ_REVIEW_MODEL          = mixtral-8x7b-32768
GEMINI_API_KEY             = AIzaSy...
GEMINI_MODEL               = gemini-2.5-flash
CLOUDFLARE_ACCOUNT_ID      = your_cloudflare_account_id
CLOUDFLARE_API_TOKEN       = your_cloudflare_workers_ai_token
CLOUDFLARE_EMBED_MODEL     = @cf/baai/bge-m3

# Telegram Alerts
TELEGRAM_BOT_TOKEN         = 123456789:ABC...
TELEGRAM_CHAT_ID           = -1001234567890

# Optional Email & Search Discovery
SMTP_HOST                  = smtp.gmail.com
SMTP_PORT                  = 587
SMTP_USERNAME              = tenders@acnabin.com
SMTP_PASSWORD              = your_google_app_password
ALERT_EMAIL_TO             = tender-committee@acnabin.com
SEARCH_PROVIDER            = google
SEARCH_API_KEY             = your_google_api_key
SEARCH_ENGINE_ID           = your_custom_search_engine_id
```

### 3.3 Deploying the Dashboard to Cloudflare Pages
1. Sign in to the [Cloudflare Dashboard](https://dash.cloudflare.com) and go to **Workers & Pages -> Create Application -> Pages -> Connect to Git**.
2. Select your repository, set the build output directory to `dashboard`, and leave the build command blank (no build step required).
3. Under **Settings -> Environment variables**, set:
   - `SUPABASE_URL` = your Supabase URL
   - `SUPABASE_ANON_KEY` = your Supabase Anon (public) key
4. Deploy the site. Your dashboard will be live at `https://<your-project>.pages.dev`.

---

## 4. Operational Workflows & Scheduling

All operations are automated via GitHub Actions scheduled workflows in `.github/workflows/`:

* `monitor.yml`: Runs at **00:00 and hourly from 08:00 to 20:00 Asia/Dhaka time** (UTC 18:00 and 02:00–14:00). Performs crawling, document downloads, extraction, AI classification, scoring, database updates, deadline tracking, and Telegram alerts.
* `weekly.yml`: Runs every Sunday at 07:00 Asia/Dhaka (01:00 UTC) to perform weekly organization discovery, search API discovery, and retention clean-up.
* `keepalive.yml`: Pings the Supabase REST endpoint twice a week to prevent the project from pausing due to inactivity on the free tier.
* `tests.yml`: Automatically runs linting, secret leak scanning, and the 23-test Pytest suite on every commit and pull request.

---

## 5. Local Development & Debugging

The system runs cleanly on any local development environment:

```powershell
# 1. Clone the repository
git clone <repo-url>
cd "Tender Agent"

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env from template
cp .env.example .env
# Edit .env with your local settings or test credentials

# 4. Run the full test suite
pytest -v tests/

# 5. Execute a single manual crawl cycle
python run_monitor.py

# 6. Execute a weekly maintenance cycle
python run_weekly.py
```

---

## 6. Business Rule Customization

All business rules live in `config/`, never in application code:

* **IFRS 9 Target Banks (`config/ifrs9_banks.json`):** Contains the 30 designated target banks with their canonical names, aliases, and official domains. Startup checks assert **exactly 30 unique banks**; any modification that violates this count will cause a loud failure.
* **Keywords (`config/keywords.json`):**
  - **Strong Terms:** Terms that independently qualify an opportunity as IFRS 9 relevant.
  - **Weak Terms:** Terms (such as "PD", "Stage 1", "ECL") that require co-occurrence with procurement terms to prevent false positives (e.g. Project Director).
  - **Bangla Terms:** Procurement and audit vocabulary in Bengali (দরপত্র, নিরীক্ষা, পরামর্শক, etc.).
  - **Irrelevant Procurement:** Terms for construction, AC maintenance, stationery, vehicles, etc., that trigger auto-rejection unless explicit advisory/audit scope is present.
* **Categories (`config/categories.json`):** Official enum codes: `IFRS9_ECL`, `AUDIT_ASSURANCE`, `RISK_CONTROL`, `ACCOUNTING_REPORTING`, `PROCESS_ADVISORY`, `TAX_VAT`, `FINANCIAL_ADVISORY`, `TRAINING`, `OTHER_PROFESSIONAL`.
* **Deterministic Scoring (`config/scoring.yaml`):** Transparent base scores and modifiers:
  - Base: `IFRS9_ECL` (60), `AUDIT_ASSURANCE` (50), `RISK_CONTROL` (50), `ACCOUNTING_REPORTING` (50), etc.
  - Modifiers: Genuine procurement (+15), Financial institution / Regulator (+10), Direct Fit (+10), Source Tier 1/2 (+5), AQR/Banking Diagnostic (+10), Low confidence (-15).
  - Priority Bands: 85–100 (VERY HIGH), 70–84 (HIGH), 55–69 (MEDIUM), 40–54 (LOW), <40 (IGNORE).

---

## 7. Free-Tier Safeguards & Hardening

* **Database Size Limits:** Extracted full text is stored only for relevant records (`OPPORTUNITY` or `MARKET_INTELLIGENCE`). Files for irrelevant records are skipped.
* **Actions Run Duration:** Average runs complete in under 2 minutes. A 4-minute time budget is enforced; if reached, the runner stops gracefully and resumes remaining sources next cycle.
* **AI Quota Tracking:** Free-tier limits (Groq 1000/day, Gemini 500/day, Cloudflare 5000/day) are monitored in the `ai_usage` table. If a provider's daily quota is exhausted, tasks fall back to secondary providers or queue as `AI_REVIEW_PENDING` without failing the run.
* **Offline / Pure Rules Mode:** Setting `AI_MODE=off` allows the full pipeline to execute using deterministic regex and keyword algorithms with zero external AI calls.

---

## 8. Human-in-the-Loop & Partner Overrides

* Automated outputs present eligibility disclaimers: *"Potentially eligible — verify tender eligibility and ACNABIN credentials."*
* From the dashboard opportunity view (`opportunity.html`), partners can override priority, review status, category, or fit type.
* Every edit is persisted to the `manual_overrides` table and **locked** against automated overwrite during subsequent crawls.

---

## 9. Troubleshooting & FAQ

* **Site blocked or SSL error:** Bangladeshi government or banking portals occasionally use self-signed certificates or block foreign IP ranges. In `config/sources.json`, set `"verify_ssl": false` for that specific source. Suspected foreign blocks are tagged as `GEO_BLOCK_SUSPECTED` in the source health monitor.
* **Scanned Bangla PDFs:** The GitHub Actions runner installs Tesseract OCR with `tesseract-ocr-ben` and `tesseract-ocr`. Scanned documents are automatically OCR'd or routed to Gemini's native PDF multimodal reader.
* **Duplicate Merging Across Banks:** The deduplication engine strictly enforces organizational boundaries: near-identical tenders from different banks are **never** merged.

---

*ACNABIN Chartered Accountants — Procurement & Opportunity Intelligence Engine.*
