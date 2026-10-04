-- ============================================================================
-- ACNABIN Tender & Opportunity Intelligence Agent — Views & RLS Policies
-- Migration: 20261001000002_views_and_rls.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Dashboard Views
-- ----------------------------------------------------------------------------

-- View: v_today_priority
-- Priority opportunities sorted by Priority -> Days to Deadline -> Score -> Confidence
CREATE OR REPLACE VIEW v_today_priority AS
SELECT 
    o.id,
    o.organization_id,
    o.organization_name,
    o.organization_type,
    o.title,
    o.reference_number,
    o.category,
    o.pipeline,
    o.outside_ifrs9_target,
    o.priority,
    o.score,
    o.fit_type,
    o.publication_date,
    o.submission_deadline,
    o.days_remaining,
    o.scope_of_work,
    o.eligibility,
    o.estimated_value,
    o.source_url,
    o.document_url,
    o.source_tier,
    o.lifecycle_status,
    o.review_status,
    o.ai_confidence,
    o.first_seen,
    o.last_checked
FROM opportunities o
WHERE o.record_type = 'OPPORTUNITY'
  AND o.priority IN ('VERY HIGH', 'HIGH')
  AND o.lifecycle_status IN ('NEW', 'ACTIVE', 'DEADLINE_APPROACHING', 'EXTENDED')
ORDER BY 
    CASE o.priority 
        WHEN 'VERY HIGH' THEN 1 
        WHEN 'HIGH' THEN 2 
        WHEN 'MEDIUM' THEN 3 
        WHEN 'LOW' THEN 4 
        ELSE 5 
    END ASC,
    COALESCE(o.days_remaining, 999) ASC,
    o.score DESC,
    o.first_seen DESC;

-- View: v_ifrs9_target
-- Displays opportunities and intelligence for the fixed 30 target banks
CREATE OR REPLACE VIEW v_ifrs9_target AS
SELECT 
    o.id,
    o.organization_id,
    o.organization_name,
    o.title,
    o.reference_number,
    o.category,
    o.priority,
    o.score,
    o.fit_type,
    o.submission_deadline,
    o.days_remaining,
    o.source_url,
    o.document_url,
    o.lifecycle_status,
    o.review_status,
    o.ai_confidence,
    o.score_breakdown,
    o.first_seen,
    o.last_checked
FROM opportunities o
WHERE o.pipeline = 'IFRS9_TARGET'
ORDER BY o.submission_deadline ASC NULLS LAST, o.score DESC;

-- View: v_general_market
-- Displays all general market opportunities across categories
CREATE OR REPLACE VIEW v_general_market AS
SELECT 
    o.id,
    o.organization_id,
    o.organization_name,
    o.organization_type,
    o.title,
    o.reference_number,
    o.category,
    o.outside_ifrs9_target,
    o.priority,
    o.score,
    o.fit_type,
    o.submission_deadline,
    o.days_remaining,
    o.source_url,
    o.document_url,
    o.lifecycle_status,
    o.review_status,
    o.ai_confidence,
    o.first_seen,
    o.last_checked
FROM opportunities o
WHERE o.pipeline = 'GENERAL_MARKET'
  AND o.record_type = 'OPPORTUNITY'
ORDER BY o.submission_deadline ASC NULLS LAST, o.score DESC;

-- View: v_source_health
-- Monitoring source status, consecutive errors, SSL overrides, geo block suspicions
CREATE OR REPLACE VIEW v_source_health AS
SELECT 
    s.id AS source_id,
    s.url,
    s.tier,
    s.enabled,
    s.requires_js,
    s.verify_ssl,
    s.rate_limit_seconds,
    s.last_checked,
    s.last_status,
    s.consecutive_failures,
    s.error_message,
    org.organization_id,
    org.canonical_name AS organization_name,
    org.sector
FROM sources s
LEFT JOIN organizations org ON s.organization_id = org.organization_id
ORDER BY s.consecutive_failures DESC, s.last_checked DESC;

-- View: v_run_summary
-- Recent monitor and discovery runs
CREATE OR REPLACE VIEW v_run_summary AS
SELECT 
    r.id,
    r.run_type,
    r.start_time,
    r.end_time,
    r.duration_seconds,
    r.status,
    r.sources_checked,
    r.sources_failed,
    r.documents_fetched,
    r.new_candidates,
    r.ai_calls,
    r.alerts_sent,
    r.error_summary
FROM runs r
ORDER BY r.start_time DESC
LIMIT 50;

-- View: v_kpis
-- Aggregate metrics for dashboard cards
CREATE OR REPLACE VIEW v_kpis AS
SELECT 
    (SELECT COUNT(*) FROM organizations) AS total_organizations,
    (SELECT COUNT(*) FROM organizations WHERE is_ifrs9_target = true) AS ifrs9_target_banks,
    (SELECT COUNT(*) FROM organizations WHERE is_ifrs9_target = false) AS general_market_orgs,
    (SELECT COUNT(*) FROM sources WHERE enabled = true) AS active_sources,
    (SELECT COUNT(*) FROM opportunities WHERE record_type = 'OPPORTUNITY' AND first_seen >= CURRENT_DATE) AS new_today,
    (SELECT COUNT(*) FROM opportunities WHERE record_type = 'OPPORTUNITY' AND priority = 'VERY HIGH' AND lifecycle_status IN ('NEW', 'ACTIVE', 'DEADLINE_APPROACHING')) AS very_high_priority,
    (SELECT COUNT(*) FROM opportunities WHERE record_type = 'OPPORTUNITY' AND priority = 'HIGH' AND lifecycle_status IN ('NEW', 'ACTIVE', 'DEADLINE_APPROACHING')) AS high_priority,
    (SELECT COUNT(*) FROM opportunities WHERE record_type = 'OPPORTUNITY' AND days_remaining IS NOT NULL AND days_remaining BETWEEN 0 AND 7 AND lifecycle_status IN ('NEW', 'ACTIVE', 'DEADLINE_APPROACHING')) AS deadlines_within_7_days,
    (SELECT COUNT(*) FROM sources WHERE last_status IN ('ERROR', 'GEO_BLOCK_SUSPECTED', 'SOURCE_REQUIRES_REVIEW')) AS source_errors,
    (SELECT COUNT(*) FROM opportunities WHERE review_status = 'AI_REVIEW_PENDING') AS pending_ai_reviews,
    (SELECT start_time FROM runs ORDER BY start_time DESC LIMIT 1) AS last_run_time,
    (SELECT status FROM runs ORDER BY start_time DESC LIMIT 1) AS last_run_status;

-- ----------------------------------------------------------------------------
-- Row Level Security (RLS) Configuration
-- ----------------------------------------------------------------------------

-- Enable RLS on all tables
ALTER TABLE app_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_intelligence ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_cache ENABLE ROW LEVEL SECURITY;

-- Helper function to check if authenticated user email is allow-listed
CREATE OR REPLACE FUNCTION is_allowlisted_user()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 
        FROM app_users 
        WHERE app_users.email = auth.jwt() ->> 'email' 
          AND app_users.is_active = true
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Service role policies (full access for worker scripts)
DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
          AND tablename IN (
              'app_users', 'organizations', 'sources', 'source_checks',
              'documents', 'document_versions', 'opportunities', 'opportunity_versions',
              'opportunity_sources', 'evidence', 'alerts', 'market_intelligence',
              'ai_reviews', 'ai_usage', 'manual_overrides', 'notes', 'runs', 'search_cache'
          )
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS "service_role_all" ON %I;', tbl);
        EXECUTE format('CREATE POLICY "service_role_all" ON %I FOR ALL TO service_role USING (true) WITH CHECK (true);', tbl);
    END LOOP;
END $$;

-- Allow-listed authenticated dashboard user policies (SELECT on views/tables)
DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
          AND tablename IN (
              'app_users', 'organizations', 'sources', 'source_checks',
              'documents', 'document_versions', 'opportunities', 'opportunity_versions',
              'opportunity_sources', 'evidence', 'alerts', 'market_intelligence',
              'ai_reviews', 'ai_usage', 'manual_overrides', 'notes', 'runs'
          )
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS "allowlist_select" ON %I;', tbl);
        EXECUTE format('CREATE POLICY "allowlist_select" ON %I FOR SELECT TO authenticated USING (is_allowlisted_user());', tbl);
    END LOOP;
END $$;

-- User notes policies (Allow-listed users can insert and read notes)
DROP POLICY IF EXISTS "allowlist_notes_insert" ON notes;
CREATE POLICY "allowlist_notes_insert" ON notes
    FOR INSERT TO authenticated
    WITH CHECK (is_allowlisted_user() AND user_email = auth.jwt() ->> 'email');

-- User manual overrides policies
DROP POLICY IF EXISTS "allowlist_overrides_insert" ON manual_overrides;
CREATE POLICY "allowlist_overrides_insert" ON manual_overrides
    FOR INSERT TO authenticated
    WITH CHECK (is_allowlisted_user() AND user_email = auth.jwt() ->> 'email');

-- Opportunity editable fields update policy
DROP POLICY IF EXISTS "allowlist_opportunity_update" ON opportunities;
CREATE POLICY "allowlist_opportunity_update" ON opportunities
    FOR UPDATE TO authenticated
    USING (is_allowlisted_user())
    WITH CHECK (is_allowlisted_user());
