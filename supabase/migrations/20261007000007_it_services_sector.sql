-- ============================================================================
-- Migration: Add IT Services sector support to tenders and source_status
-- ============================================================================

-- 1. Update check constraint on tenders.sector
ALTER TABLE tenders DROP CONSTRAINT IF EXISTS tenders_sector_check;
ALTER TABLE tenders ADD CONSTRAINT tenders_sector_check CHECK (sector IN ('BANK', 'NGO', 'IT'));

-- 2. Seed IT Organizations
INSERT INTO organizations (
    organization_id, canonical_name, aliases, organization_type, sector,
    official_domain, is_ifrs9_target, source_status, last_verified, notes
)
VALUES 
    ('agg_alltender_ict', 'Alltender ICT & IT Services', '["Alltender ICT", "Alltender IT"]'::jsonb, 'AGGREGATOR', 'it', 'alltender.com', false, 'OK', '2026-10-07', 'Alltender ICT and Software live tenders aggregator'),
    ('gov_bcc', 'Bangladesh Computer Council (BCC)', '["BCC", "বাংলাদেশ কম্পিউটার কাউন্সিল"]'::jsonb, 'GOVERNMENT_AGENCY', 'it', 'bcc.gov.bd', false, 'OK', '2026-10-07', 'Statutory body under ICT Division'),
    ('gov_ictd', 'Information & Communication Technology Division (ICTD)', '["ICT Division", "তথ্য ও যোগাযোগ প্রযুক্তি বিভাগ"]'::jsonb, 'GOVERNMENT_MINISTRY', 'it', 'ictd.gov.bd', false, 'OK', '2026-10-07', 'Ministry of Posts, Telecommunications and Information Technology')
ON CONFLICT (organization_id) DO UPDATE 
SET canonical_name = EXCLUDED.canonical_name,
    aliases = EXCLUDED.aliases,
    sector = EXCLUDED.sector,
    official_domain = EXCLUDED.official_domain;
