# ACNABIN Tender Monitoring

Monitors the tender, procurement and notice pages of **banks** and **NGOs / development organizations** in Bangladesh and answers one question:

> What active tenders are the monitored organizations publishing, and which of them matter to ACNABIN?

```
Home
 ├── Bank   ── General  (all active bank tenders)
 │          └─ Priority (active + relevant to ACNABIN; IFRS 9 / ECL flagged)
 └── NGO    ── General  (all active NGO tenders)
            └─ Priority (active + relevant to ACNABIN)
```

- **General** = every *active* opportunity found on a monitored source, whatever the subject (furniture, IT equipment, construction, audit…).
- **Priority** = active **and** relevant to ACNABIN's services: audit & assurance, IT/IS audit, accounting & financial reporting, IFRS / IFRS 9 / ECL, risk & internal control, tax & VAT, financial & management advisory, professional training.
- **IFRS 9 / ECL** is a Priority signal, not the definition of Priority. The 30 IFRS 9 target banks are all monitored for *every* tender, and IFRS 9 / ECL notices are flagged.

## How a run works

```
config/sources.json → fetch page → extract listings → read notice page / tender PDF
  → dates (publication, deadline) → open/closed status → ACTIVE? → General
  → ACNABIN relevance → Priority (+ IFRS 9 flag) → de-duplicate → Supabase → dashboard
```

All logic is deterministic (no LLM calls). Code lives in `app/`:

| Module | Responsibility |
|---|---|
| `app/pipeline.py` | One monitoring run; ties the steps together |
| `app/crawler/crawler.py` | HTTP fetching, politeness delay, detection of 404 / soft-404 / bot-challenge pages |
| `app/parsers/html_parser.py` | Tender tables (columns identified from headers), link listings, detail cards |
| `app/parsers/document_parser.py` | Text of the first pages of PDF / DOCX / XLSX notices (OCR when Tesseract is installed) |
| `app/parsers/date_cleaner.py` | Date parsing and labelling (deadline vs publication date) |
| `app/classification/status.py` | Closed / cancelled / awarded detection and the ACTIVE rule |
| `app/classification/relevance.py` | Priority categories and IFRS 9 / ECL detection, driven by `config/relevance.json` |
| `app/classification/dedupe.py` | Stable tender ids and duplicate merging |
| `app/db/supabase.py` | Storage (`tenders`, `source_status`, `runs`) |
| `app/alerts/telegram.py` | Optional Telegram message for each newly found Priority tender |

### Active rule

A tender is **active** when its status is open and

1. it has a deadline and the deadline has not passed, **or**
2. no deadline is stated and it was published within the last **7 days**, **or**
3. no date is stated at all, but it newly appeared on a page that was already being monitored, within the last 7 days.

A stated deadline always decides (a past deadline is expired even if the notice is recent). Notices marked closed, cancelled, withdrawn or awarded are never active. The rule is evaluated at query time by the `v_active_tenders` view, so tenders expire automatically; nothing is tied to a fixed date.

### Dates

Dates are parsed into real dates (`05/10/2026`, `2026-10-05`, `05 Oct 2026`, `October 5, 2026`, `01-Oct-2026`, Bangla digits and month names). Numeric dates are read day-first (Bangladesh convention). A date only counts as a deadline or a publication date when a label says so ("Closing Date", "Last date of submission", "Published", "Date:" on a memo, table column headers…). If no date can be found, the field stays empty; dates are never estimated.

### Relevance

`config/relevance.json` holds every phrase list and can be edited without touching code:

- `categories`: per service area, `phrases` (matched on the title and listing/notice text) and `document_phrases` (specific phrases also matched in tender documents, e.g. "appointment of external auditor"). Generic words like "audit" are deliberately **not** matched in PDF text, because bidding documents always mention "audited financial statements", "VAT registration" etc.
- `ifrs9.strong`: terms that alone indicate IFRS 9 work (IFRS 9 / IFRS-9 / IFRS9, Expected Credit Loss, ECL model / methodology / validation, financial instrument impairment…).
- `ifrs9.contextual`: generic terms (ECL, PD, LGD, impairment model, credit risk model) that only count with IFRS 9 context nearby. "Credit officer recruitment" or "loan collection services" are not IFRS 9.
- `exclusions`: phrases removed before matching (energy audit, audited financial statements, Audit Department, Oracle Audit Vault…).
- `priority_veto`: titles that are never Priority (recruitment, vacancies, sale of old assets, auctions).
- `closed_status`: wording that marks a notice as closed / cancelled / awarded.

## Configuration

| File | Content |
|---|---|
| `config/ifrs9_banks.json` | The fixed list of **30 IFRS 9 target banks** (startup fails if it is not exactly 30) |
| `config/organizations.json` | Organization names, types and sectors (bank / NGO) |
| `config/sources.json` | Tender pages to crawl. Options: `verify_ssl`, `requires_js` (render with Playwright), `country_filter` (global INGO pages: keep only Bangladesh notices), `enabled` + `note` |
| `config/relevance.json` | Relevance rules (see above) |
| `config/settings.yaml` | Active window (7 days), crawler limits, run budget |

### Aggregator: Bdjobs Tender/EOI

`src_agg_bdjobs` reads the JSON feed behind the Tender/EOI section of [bdjobs.com/h/](https://bdjobs.com/h/) (`"type": "bdjobs_json"`). It covers many NGOs, INGOs and UN agencies whose own websites have no usable tender page. Each notice is attributed to the organization that published it (matched to `config/organizations.json` by name; unknown organizations are added as new ones, financial institutions under Bank). The dashboard marks these rows "via Bdjobs.com". When the same notice is also found on the organization's own page (same organization, same deadline, matching title), only the official copy is shown.

### Admin page (add or correct URLs without editing files)

Dashboard → **Admin** (`admin.html`). After signing in you can:

- **Add a tender page**: enter the URL, pick an existing organization (or "New organization…" with a name and Bank/NGO section), and set options (needs JavaScript, ignore SSL errors, keep only Bangladesh notices).
- **Correct a broken source**: every source that failed or showed no notices in the last run is listed; enter the real URL and save.
- **Manage** what was added: see the result of its last check, switch monitoring on/off, or remove it (a removed correction falls back to the address in `config/sources.json`).

Entries are stored in the `admin_sources` table and merged with `config/sources.json` at the start of every run. Only signed-in users listed in `app_users` (active) can write; the database enforces this with row-level security.

To give someone access: Supabase dashboard → Authentication → Users → **Add user** (email + password, auto-confirm), then add the same email to the `app_users` table.

### Keeping sources healthy

Many organizations move their tender pages. Every run records each source's result in `source_status` (dashboard → **Sources**). To repair broken sources:

```bash
python scripts/check_sources.py            # all sources
python scripts/check_sources.py --sector NGO
```

The script checks every configured page and, for broken or empty ones, lists tender/procurement pages linked from the organization's **own homepage**, with how many listings each yields. Review the candidates and update `config/sources.json`. URLs are never constructed by guesswork. The same check runs weekly in GitHub Actions (`weekly.yml`) and uploads the report.

Sources that could not be repaired on 2026-10-05 remain enabled and are reported as errors (some sites block automated access, some domains no longer resolve). The e-GP homepage is disabled (login portal), and CCDB is disabled because its domain currently serves unrelated content.

## Running

```bash
pip install -r requirements.txt
python -m playwright install chromium     # only needed for sources with requires_js

python run_monitor.py                     # all sources, writes to Supabase if configured
python run_monitor.py --sector NGO        # one sector
python run_monitor.py --source src_07_sonali_tender
python run_monitor.py --local             # do not write to Supabase; writes data/local_run.json

pytest                                    # test suite
```

Environment variables: see `.env.example` (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, optional Telegram).

### Database

Apply migrations with the Supabase CLI (`supabase db push`). `20261005000004_tenders_general_priority.sql` creates:

- `tenders`: one row per notice (organization, title, description, reference, published date, deadline, status, priority, IFRS 9 flag, categories, matched keywords, source page, notice/document link)
- `source_status`: last result per source
- `v_active_tenders`: active tenders only (the dashboard reads this)
- `v_last_run`: time of the last completed run

The tables and views of the previous design (`opportunities`, `v_general_market`, …) are left in place and are no longer used; they can be dropped once the new dashboard is deployed.

### Automation (GitHub Actions)

- `monitor.yml`: hourly 08:00–20:00 and at 00:00 Asia/Dhaka; runs `run_monitor.py`
- `weekly.yml`: Sunday source health check (`scripts/check_sources.py`)
- `tests.yml`: test suite on every push
- `deploy-dashboard.yml`: deploys `dashboard/` to Cloudflare Pages on changes
- `keepalive.yml`: keeps the free Supabase project awake

### Dashboard

Static pages in `dashboard/` (`index.html`, `bank.html`, `ngo.html`, `sources.html`) reading Supabase with the public anon key (`dashboard/js/config.js`). Filters: search, organization, category, deadline window, publication date, and on Bank: IFRS 9 / ECL only and 30 target banks only. Results can be exported to CSV.
