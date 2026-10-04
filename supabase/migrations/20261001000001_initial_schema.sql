-- ============================================================================
-- ACNABIN Tender & Opportunity Intelligence Agent — Database Schema
-- Migration: 20261001000001_initial_schema.sql
-- ============================================================================

-- Enable pgvector extension for semantic embeddings and deduplication
CREATE EXTENSION IF NOT EXISTS vector;

-- Enums
DO $$ BEGIN
    CREATE TYPE record_type_enum AS ENUM ('OPPORTUNITY', 'MARKET_INTELLIGENCE', 'IRRELEVANT');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE pipeline_enum AS ENUM ('IFRS9_TARGET', 'GENERAL_MARKET');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE lifecycle_status_enum AS ENUM (
        'NEW', 'ACTIVE', 'DEADLINE_APPROACHING', 'SUBMISSION_CLOSED',
        'EXTENDED', 'CANCELLED', 'RETENDERED', 'AWARDED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE review_status_enum AS ENUM (
        'AI_REVIEW_PENDING', 'REVIEW_REQUIRED', 'VERIFIED', 'SHORTLISTED', 'NOT_PURSUING'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE fit_type_enum AS ENUM ('DIRECT_FIT', 'PARTNERSHIP_REQUIRED', 'NOT_SUITABLE');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE source_verification_enum AS ENUM ('VERIFIED', 'UNVERIFIED');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE source_status_enum AS ENUM (
        'OK', 'ERROR', 'GEO_BLOCK_SUSPECTED', 'SOURCE_REQUIRES_REVIEW', 'PENDING_VERIFICATION'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE priority_enum AS ENUM ('VERY HIGH', 'HIGH', 'MEDIUM', 'LOW', 'IGNORE');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE confidence_enum AS ENUM ('HIGH', 'MEDIUM', 'LOW');
EXCEPTION WHEN duplicate_object THEN null; END $$;

-- 1. App Users (Allow-list for Dashboard Access)
CREATE TABLE IF NOT EXISTS app_users (
    email TEXT PRIMARY KEY,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'reviewer', 'viewer')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Organizations Registry
CREATE TABLE IF NOT EXISTS organizations (
    organization_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    organization_type TEXT NOT NULL,
    sector TEXT NOT NULL,
    official_domain TEXT,
    procurement_url TEXT,
    tender_url TEXT,
    notice_url TEXT,
    is_ifrs9_target BOOLEAN NOT NULL DEFAULT false,
    source_status source_status_enum NOT NULL DEFAULT 'OK',
    last_verified DATE,
    last_checked TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Sources
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    organization_id TEXT REFERENCES organizations(organization_id) ON DELETE SET NULL,
    tier INTEGER NOT NULL DEFAULT 1 CHECK (tier BETWEEN 1 AND 4),
    requires_js BOOLEAN NOT NULL DEFAULT false,
    verify_ssl BOOLEAN NOT NULL DEFAULT true,
    rate_limit_seconds NUMERIC(5,2) NOT NULL DEFAULT 5.0,
    enabled BOOLEAN NOT NULL DEFAULT true,
    etag TEXT,
    last_modified TEXT,
    last_checked TIMESTAMPTZ,
    last_status source_status_enum NOT NULL DEFAULT 'OK',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Source Checks History
CREATE TABLE IF NOT EXISTS source_checks (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT REFERENCES sources(id) ON DELETE CASCADE,
    check_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status INTEGER,
    duration_ms INTEGER,
    error TEXT,
    items_found INTEGER DEFAULT 0,
    new_items INTEGER DEFAULT 0
);

-- 5. Documents
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, -- document_hash
    url TEXT NOT NULL,
    document_hash TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    title TEXT,
    publication_date TIMESTAMPTZ,
    last_modified TIMESTAMPTZ,
    etag TEXT,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    local_storage_path TEXT,
    text_extracted TEXT,
    is_scanned BOOLEAN NOT NULL DEFAULT false,
    ocr_applied BOOLEAN NOT NULL DEFAULT false
);

-- 6. Document Versions
CREATE TABLE IF NOT EXISTS document_versions (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    document_hash TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_type TEXT,
    diff_summary TEXT
);

-- 7. Opportunities (Core Table)
CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    organization_id TEXT REFERENCES organizations(organization_id) ON DELETE SET NULL,
    organization_name TEXT NOT NULL,
    organization_type TEXT,
    title TEXT NOT NULL,
    reference_number TEXT,
    tender_type TEXT,
    category TEXT NOT NULL,
    pipeline pipeline_enum NOT NULL DEFAULT 'GENERAL_MARKET',
    outside_ifrs9_target BOOLEAN NOT NULL DEFAULT false,
    priority priority_enum NOT NULL DEFAULT 'LOW',
    score INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    fit_type fit_type_enum NOT NULL DEFAULT 'DIRECT_FIT',
    publication_date TIMESTAMPTZ,
    publication_date_raw TEXT,
    submission_deadline TIMESTAMPTZ,
    deadline_raw TEXT,
    days_remaining INTEGER,
    opening_datetime TIMESTAMPTZ,
    prebid_meeting TIMESTAMPTZ,
    clarification_deadline TIMESTAMPTZ,
    scope_of_work TEXT,
    eligibility TEXT,
    eligibility_concerns JSONB DEFAULT '[]'::jsonb,
    minimum_experience TEXT,
    required_certifications JSONB DEFAULT '[]'::jsonb,
    required_team TEXT,
    required_documents JSONB DEFAULT '[]'::jsonb,
    bid_security TEXT,
    tender_fee TEXT,
    contract_period TEXT,
    estimated_value TEXT,
    submission_method TEXT,
    submission_address TEXT,
    contact_person TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    source_url TEXT NOT NULL,
    document_url TEXT,
    source_tier INTEGER DEFAULT 1,
    source_verification source_verification_enum NOT NULL DEFAULT 'VERIFIED',
    record_type record_type_enum NOT NULL DEFAULT 'OPPORTUNITY',
    lifecycle_status lifecycle_status_enum NOT NULL DEFAULT 'NEW',
    review_status review_status_enum NOT NULL DEFAULT 'AI_REVIEW_PENDING',
    is_baseline BOOLEAN NOT NULL DEFAULT false,
    ai_confidence confidence_enum NOT NULL DEFAULT 'MEDIUM',
    extraction_result JSONB DEFAULT '{}'::jsonb,
    review_result JSONB DEFAULT '{}'::jsonb,
    score_breakdown JSONB DEFAULT '{}'::jsonb,
    embedding vector(1024),
    content_hash TEXT NOT NULL,
    document_hash TEXT,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 8. Opportunity Versions (Amendments / Extensions)
CREATE TABLE IF NOT EXISTS opportunity_versions (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL DEFAULT 1,
    change_type TEXT NOT NULL,
    change_summary TEXT,
    previous_deadline TIMESTAMPTZ,
    new_deadline TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9. Opportunity Sources (Multiple discovery sources per tender)
CREATE TABLE IF NOT EXISTS opportunity_sources (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    tier INTEGER NOT NULL DEFAULT 1,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. Evidence (Quotes from document pages)
CREATE TABLE IF NOT EXISTS evidence (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    page_number INTEGER,
    section_name TEXT,
    quoted_text TEXT NOT NULL,
    verified_against_source BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. Alerts Log
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE CASCADE,
    alert_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'SENT'
);

-- 12. Market Intelligence
CREATE TABLE IF NOT EXISTS market_intelligence (
    id TEXT PRIMARY KEY,
    organization_id TEXT REFERENCES organizations(organization_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT,
    source_url TEXT NOT NULL,
    publication_date TIMESTAMPTZ,
    category TEXT,
    content_hash TEXT NOT NULL,
    tags JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. AI Reviews History
CREATE TABLE IF NOT EXISTS ai_reviews (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    input_data JSONB,
    output_data JSONB,
    is_disagreement BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14. AI Usage Tracking (Free-tier quotas)
CREATE TABLE IF NOT EXISTS ai_usage (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    call_count INTEGER NOT NULL DEFAULT 0,
    prompt_tokens BIGINT NOT NULL DEFAULT 0,
    completion_tokens BIGINT NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_provider_model_date UNIQUE (provider, model, usage_date)
);

-- 15. Manual Overrides (Human in the loop locks)
CREATE TABLE IF NOT EXISTS manual_overrides (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    original_value TEXT,
    new_value TEXT NOT NULL,
    user_email TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 16. User Notes & Quick Tags
CREATE TABLE IF NOT EXISTS notes (
    id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    user_email TEXT NOT NULL,
    note_text TEXT NOT NULL,
    quick_tags JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 17. Monitor Runs Summary
CREATE TABLE IF NOT EXISTS runs (
    id BIGSERIAL PRIMARY KEY,
    run_type TEXT NOT NULL DEFAULT 'monitor',
    start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_time TIMESTAMPTZ,
    duration_seconds NUMERIC(8,2),
    status TEXT NOT NULL DEFAULT 'RUNNING',
    sources_checked INTEGER DEFAULT 0,
    sources_failed INTEGER DEFAULT 0,
    documents_fetched INTEGER DEFAULT 0,
    new_candidates INTEGER DEFAULT 0,
    ai_calls INTEGER DEFAULT 0,
    alerts_sent INTEGER DEFAULT 0,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 18. Search Cache
CREATE TABLE IF NOT EXISTS search_cache (
    id BIGSERIAL PRIMARY KEY,
    query_hash TEXT NOT NULL UNIQUE,
    query_text TEXT NOT NULL,
    provider TEXT NOT NULL,
    result_urls JSONB DEFAULT '[]'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for performance & dedupe
CREATE INDEX IF NOT EXISTS idx_opportunities_ref_num ON opportunities(reference_number);
CREATE INDEX IF NOT EXISTS idx_opportunities_org_id ON opportunities(organization_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_deadline ON opportunities(submission_deadline);
CREATE INDEX IF NOT EXISTS idx_opportunities_priority ON opportunities(priority);
CREATE INDEX IF NOT EXISTS idx_opportunities_review_status ON opportunities(review_status);
CREATE INDEX IF NOT EXISTS idx_opportunities_content_hash ON opportunities(content_hash);
CREATE INDEX IF NOT EXISTS idx_opportunities_document_hash ON opportunities(document_hash);
CREATE INDEX IF NOT EXISTS idx_opportunities_pipeline ON opportunities(pipeline);
CREATE INDEX IF NOT EXISTS idx_sources_org_id ON sources(organization_id);
CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);
CREATE INDEX IF NOT EXISTS idx_alerts_dedupe_key ON alerts(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_manual_overrides_opp_field ON manual_overrides(opportunity_id, field_name);
