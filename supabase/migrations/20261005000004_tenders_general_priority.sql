-- ============================================================================
-- ACNABIN Tender Monitor — simplified data model
--
--   tenders          one row per tender notice found on a monitored source
--   source_status    last crawl result per source (for troubleshooting broken sources)
--   v_active_tenders active tenders only; the dashboard's General = all rows,
--                    Priority = rows where is_priority
--
-- ACTIVE rule (also implemented in app/classification/status.py):
--   status = 'OPEN' AND (
--        deadline >= now()
--     OR (deadline IS NULL AND published_date >= today(Asia/Dhaka) - 7 days)
--     OR (deadline IS NULL AND published_date IS NULL AND NOT is_baseline
--         AND first_seen >= now() - 7 days)   -- appeared on an already-monitored page
--   )
-- Because the rule is evaluated in the view at query time, tenders expire automatically.
-- ============================================================================

CREATE TABLE IF NOT EXISTS tenders (
    id                 TEXT PRIMARY KEY,
    sector             TEXT NOT NULL CHECK (sector IN ('BANK', 'NGO')),
    organization_id    TEXT NOT NULL,
    organization_name  TEXT NOT NULL,
    organization_type  TEXT,
    is_target_bank     BOOLEAN NOT NULL DEFAULT false,
    title              TEXT NOT NULL,
    description        TEXT,
    reference_number   TEXT,
    published_date     DATE,
    deadline           TIMESTAMPTZ,
    deadline_has_time  BOOLEAN NOT NULL DEFAULT false,
    status             TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED', 'AWARDED')),
    is_priority        BOOLEAN NOT NULL DEFAULT false,
    is_ifrs9           BOOLEAN NOT NULL DEFAULT false,
    categories         TEXT[] NOT NULL DEFAULT '{}',
    matched_keywords   TEXT[] NOT NULL DEFAULT '{}',
    source_id          TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    notice_url         TEXT,
    document_url       TEXT,
    document_text      TEXT,
    document_checked   BOOLEAN NOT NULL DEFAULT false,
    is_baseline        BOOLEAN NOT NULL DEFAULT false,
    first_seen         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenders_sector ON tenders(sector);
CREATE INDEX IF NOT EXISTS idx_tenders_deadline ON tenders(deadline);
CREATE INDEX IF NOT EXISTS idx_tenders_published ON tenders(published_date);
CREATE INDEX IF NOT EXISTS idx_tenders_org ON tenders(organization_id);

CREATE TABLE IF NOT EXISTS source_status (
    source_id             TEXT PRIMARY KEY,
    organization_id       TEXT NOT NULL,
    organization_name     TEXT NOT NULL,
    sector                TEXT NOT NULL,
    is_target_bank        BOOLEAN NOT NULL DEFAULT false,
    url                   TEXT NOT NULL,
    last_checked          TIMESTAMPTZ,
    first_ok              TIMESTAMPTZ,
    last_ok               TIMESTAMPTZ,
    ok                    BOOLEAN NOT NULL DEFAULT false,
    http_status           INTEGER,
    error                 TEXT,
    listings_found        INTEGER NOT NULL DEFAULT 0,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0
);

-- Row level security: the worker writes with the service role; the dashboard reads
-- (public tender information only) with the anon key.
ALTER TABLE tenders ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_status ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all" ON tenders;
CREATE POLICY "service_role_all" ON tenders FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "dashboard_read" ON tenders;
CREATE POLICY "dashboard_read" ON tenders FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "service_role_all" ON source_status;
CREATE POLICY "service_role_all" ON source_status FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "dashboard_read" ON source_status;
CREATE POLICY "dashboard_read" ON source_status FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "dashboard_read" ON runs;
CREATE POLICY "dashboard_read" ON runs FOR SELECT TO anon, authenticated USING (true);

GRANT SELECT ON tenders, source_status, runs TO anon, authenticated;

-- Active tenders (General). Priority = WHERE is_priority.
DROP VIEW IF EXISTS v_active_tenders;
CREATE VIEW v_active_tenders WITH (security_invoker = on) AS
SELECT
    t.id, t.sector, t.organization_id, t.organization_name, t.organization_type,
    t.is_target_bank, t.title, t.description, t.reference_number,
    t.published_date, t.deadline, t.deadline_has_time,
    t.is_priority, t.is_ifrs9, t.categories, t.matched_keywords,
    t.source_url, t.notice_url, t.document_url, t.first_seen
FROM tenders t
WHERE t.status = 'OPEN'
  AND (
        t.deadline >= now()
     OR (t.deadline IS NULL AND t.published_date >= ((now() AT TIME ZONE 'Asia/Dhaka')::date - 7))
     OR (t.deadline IS NULL AND t.published_date IS NULL AND NOT t.is_baseline
         AND t.first_seen >= now() - interval '7 days')
  );

GRANT SELECT ON v_active_tenders TO anon, authenticated;

-- Latest completed monitor run (shown as "Last updated" on the dashboard)
DROP VIEW IF EXISTS v_last_run;
CREATE VIEW v_last_run WITH (security_invoker = on) AS
SELECT id, start_time, end_time, status, sources_checked, sources_failed
FROM runs
WHERE run_type = 'monitor' AND status = 'COMPLETED'
ORDER BY end_time DESC NULLS LAST
LIMIT 1;

GRANT SELECT ON v_last_run TO anon, authenticated;

-- The views and tables of the previous score/pipeline model (v_today_priority, v_ifrs9_target,
-- v_general_market, v_kpis, opportunities, ...) are left untouched so the currently deployed
-- dashboard keeps working until the new one is deployed. They can be dropped afterwards.
