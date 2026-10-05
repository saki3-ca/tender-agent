-- ============================================================================
-- Admin-managed sources (dashboard → Admin)
--
-- One row either
--   * replaces the URL of a source in config/sources.json   (source_id = that id), or
--   * adds a new tender page                                  (source_id = 'src_admin_…').
-- The monitor merges these rows with config/sources.json at the start of every run.
-- Only signed-in users listed in app_users (is_active) can write.
-- ============================================================================

CREATE TABLE IF NOT EXISTS admin_sources (
    source_id          TEXT PRIMARY KEY DEFAULT ('src_admin_' || substr(md5(random()::text || clock_timestamp()::text), 1, 10)),
    url                TEXT NOT NULL CHECK (url ~* '^https?://[^\s/$.?#].[^\s]*$'),
    organization_id    TEXT,
    organization_name  TEXT NOT NULL,
    sector             TEXT NOT NULL CHECK (sector IN ('BANK', 'NGO')),
    requires_js        BOOLEAN NOT NULL DEFAULT false,
    verify_ssl         BOOLEAN NOT NULL DEFAULT true,
    country_filter     BOOLEAN NOT NULL DEFAULT false,
    enabled            BOOLEAN NOT NULL DEFAULT true,
    notes              TEXT,
    added_by           TEXT DEFAULT (auth.jwt() ->> 'email'),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION admin_sources_touch() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS admin_sources_touch ON admin_sources;
CREATE TRIGGER admin_sources_touch BEFORE UPDATE ON admin_sources
    FOR EACH ROW EXECUTE FUNCTION admin_sources_touch();

ALTER TABLE admin_sources ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all" ON admin_sources;
CREATE POLICY "service_role_all" ON admin_sources FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "admin_read" ON admin_sources;
CREATE POLICY "admin_read" ON admin_sources FOR SELECT TO authenticated USING (is_allowlisted_user());
DROP POLICY IF EXISTS "admin_insert" ON admin_sources;
CREATE POLICY "admin_insert" ON admin_sources FOR INSERT TO authenticated WITH CHECK (is_allowlisted_user());
DROP POLICY IF EXISTS "admin_update" ON admin_sources;
CREATE POLICY "admin_update" ON admin_sources FOR UPDATE TO authenticated USING (is_allowlisted_user()) WITH CHECK (is_allowlisted_user());
DROP POLICY IF EXISTS "admin_delete" ON admin_sources;
CREATE POLICY "admin_delete" ON admin_sources FOR DELETE TO authenticated USING (is_allowlisted_user());

GRANT SELECT, INSERT, UPDATE, DELETE ON admin_sources TO authenticated;

-- Lets the Admin page tell a signed-in user whether they are on the allow-list.
CREATE OR REPLACE FUNCTION am_i_admin() RETURNS BOOLEAN
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$ SELECT is_allowlisted_user() $$;
GRANT EXECUTE ON FUNCTION am_i_admin() TO authenticated;
