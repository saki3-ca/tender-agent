-- IT Services page: subject flag and IT Priority (capabilities of ACNABIN and its MoU IT partners).
-- An IT tender keeps its organization's sector (a bank's software RFP is also a Bank tender);
-- the IT page lists every active tender with is_it.
ALTER TABLE tenders ADD COLUMN IF NOT EXISTS is_it BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tenders ADD COLUMN IF NOT EXISTS it_priority BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tenders ADD COLUMN IF NOT EXISTS it_categories TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tenders ADD COLUMN IF NOT EXISTS it_partners TEXT[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS tenders_is_it_idx ON tenders (is_it) WHERE is_it;

DROP VIEW IF EXISTS v_active_tenders;
CREATE VIEW v_active_tenders WITH (security_invoker = on) AS
SELECT
    t.id, t.sector, t.organization_id, t.organization_name, t.organization_type,
    t.is_target_bank, t.title, t.description, t.reference_number,
    t.published_date, t.deadline, t.deadline_has_time,
    t.is_priority, t.is_ifrs9, t.categories, t.matched_keywords,
    t.source_url, t.notice_url, t.document_url, t.first_seen,
    t.members_only, t.is_it, t.it_priority, t.it_categories, t.it_partners
FROM tenders t
WHERE t.status = 'OPEN'
  AND (
        t.deadline >= now()
     OR (t.deadline IS NULL AND t.published_date >= ((now() AT TIME ZONE 'Asia/Dhaka')::date - 7))
     OR (t.deadline IS NULL AND t.published_date IS NULL AND NOT t.is_baseline
         AND t.first_seen >= now() - interval '7 days')
  );

GRANT SELECT ON v_active_tenders TO anon, authenticated;
