-- Tenders from paid subscription services (Alltender.com) may not be republished:
-- they are stored as members_only and are readable only by signed-in users on the admin allow-list.
ALTER TABLE tenders ADD COLUMN IF NOT EXISTS members_only BOOLEAN NOT NULL DEFAULT FALSE;

DROP POLICY IF EXISTS "dashboard_read" ON tenders;
DROP POLICY IF EXISTS "public_read" ON tenders;
DROP POLICY IF EXISTS "members_read" ON tenders;
CREATE POLICY "public_read" ON tenders FOR SELECT TO anon USING (NOT members_only);
CREATE POLICY "members_read" ON tenders FOR SELECT TO authenticated
    USING (NOT members_only OR is_allowlisted_user());

-- v_active_tenders (security_invoker) applies these policies; it now also returns members_only.
CREATE OR REPLACE VIEW v_active_tenders WITH (security_invoker = on) AS
SELECT
    t.id, t.sector, t.organization_id, t.organization_name, t.organization_type,
    t.is_target_bank, t.title, t.description, t.reference_number,
    t.published_date, t.deadline, t.deadline_has_time,
    t.is_priority, t.is_ifrs9, t.categories, t.matched_keywords,
    t.source_url, t.notice_url, t.document_url, t.first_seen,
    t.members_only
FROM tenders t
WHERE t.status = 'OPEN'
  AND (
        t.deadline >= now()
     OR (t.deadline IS NULL AND t.published_date >= ((now() AT TIME ZONE 'Asia/Dhaka')::date - 7))
     OR (t.deadline IS NULL AND t.published_date IS NULL AND NOT t.is_baseline
         AND t.first_seen >= now() - interval '7 days')
  );

GRANT SELECT ON v_active_tenders TO anon, authenticated;
