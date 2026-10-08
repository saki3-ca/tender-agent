-- ============================================================================
-- Admin through the ACNABIN Task Tracker (no separate sign-in)
--
-- The dashboard's Admin section is shown only to Task Tracker Admins. The portal gives the dashboard a
-- short-lived bridge token; every admin function below asks the Task Tracker database whether that token
-- belongs to an Admin (supabase_tender_agent_bridge.sql in the Task Tracker project) before it does anything.
--
-- Before running: run supabase_tender_agent_bridge.sql in the TASK TRACKER Supabase project.
-- Then run this file here, and check the two values in the INSERT below (tracker URL and public anon key).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS http WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS tracker_bridge_config (
    id               INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tracker_url      TEXT NOT NULL,
    tracker_anon_key TEXT NOT NULL
);
ALTER TABLE tracker_bridge_config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON tracker_bridge_config FROM anon, authenticated;

-- The Task Tracker project URL and its public (anon / publishable) key
INSERT INTO tracker_bridge_config (id, tracker_url, tracker_anon_key)
VALUES (1, 'https://sjqcoxosfuvsrqoglqxn.supabase.co', 'sb_publishable_YFlLmEIMXg6uVFSXi3mYaw_e_cFxP4a')
ON CONFLICT (id) DO UPDATE SET tracker_url = EXCLUDED.tracker_url, tracker_anon_key = EXCLUDED.tracker_anon_key;

-- TRUE when the Task Tracker says this token belongs to an active Admin
CREATE OR REPLACE FUNCTION _ta_is_admin(p_token TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions
AS $$
DECLARE
    cfg  tracker_bridge_config%ROWTYPE;
    resp extensions.http_response;
BEGIN
    IF p_token IS NULL OR p_token !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
    SELECT * INTO cfg FROM tracker_bridge_config WHERE id = 1;
    IF NOT FOUND THEN RETURN FALSE; END IF;

    PERFORM extensions.http_set_curlopt('CURLOPT_TIMEOUT', '8');
    resp := extensions.http((
        'POST',
        cfg.tracker_url || '/rest/v1/rpc/app_tender_agent_bridge_verify',
        ARRAY[extensions.http_header('apikey', cfg.tracker_anon_key)],
        'application/json',
        jsonb_build_object('p_token', p_token)::text
    )::extensions.http_request);

    RETURN resp.status = 200 AND btrim(resp.content) = 'true';
EXCEPTION WHEN OTHERS THEN
    RETURN FALSE;
END;
$$;
REVOKE ALL ON FUNCTION _ta_is_admin(TEXT) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION ta_admin_check(p_token TEXT) RETURNS BOOLEAN
LANGUAGE sql SECURITY DEFINER SET search_path = public, extensions
AS $$ SELECT _ta_is_admin(p_token) $$;

-- Everything the Admin page lists: last result per source, and the managed (added / corrected) sources.
-- NULL when the caller is not an Admin.
CREATE OR REPLACE FUNCTION ta_admin_data(p_token TEXT) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions
AS $$
BEGIN
    IF NOT _ta_is_admin(p_token) THEN RETURN NULL; END IF;
    RETURN jsonb_build_object(
        'statuses', COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.organization_name) FROM source_status s), '[]'::jsonb),
        'sources',  COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.created_at DESC) FROM admin_sources a), '[]'::jsonb)
    );
END;
$$;

-- Add a new source
CREATE OR REPLACE FUNCTION ta_admin_source_add(p_token TEXT, p_row JSONB) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions
AS $$
BEGIN
    IF NOT _ta_is_admin(p_token) THEN RAISE EXCEPTION 'Not allowed' USING ERRCODE = '42501'; END IF;
    INSERT INTO admin_sources (url, organization_id, organization_name, sector, notes,
                               requires_js, verify_ssl, country_filter, enabled, added_by)
    VALUES (
        btrim(p_row->>'url'),
        NULLIF(btrim(COALESCE(p_row->>'organization_id', '')), ''),
        btrim(p_row->>'organization_name'),
        p_row->>'sector',
        NULLIF(btrim(COALESCE(p_row->>'notes', '')), ''),
        COALESCE((p_row->>'requires_js')::boolean, false),
        COALESCE((p_row->>'verify_ssl')::boolean, true),
        COALESCE((p_row->>'country_filter')::boolean, false),
        COALESCE((p_row->>'enabled')::boolean, true),
        'task-tracker-admin'
    );
END;
$$;

-- Correct the URL of an existing source (or re-save a managed one)
CREATE OR REPLACE FUNCTION ta_admin_source_upsert(p_token TEXT, p_row JSONB) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions
AS $$
BEGIN
    IF NOT _ta_is_admin(p_token) THEN RAISE EXCEPTION 'Not allowed' USING ERRCODE = '42501'; END IF;
    INSERT INTO admin_sources (source_id, url, organization_id, organization_name, sector, enabled, added_by)
    VALUES (
        p_row->>'source_id', btrim(p_row->>'url'),
        NULLIF(btrim(COALESCE(p_row->>'organization_id', '')), ''),
        btrim(p_row->>'organization_name'), p_row->>'sector',
        COALESCE((p_row->>'enabled')::boolean, true), 'task-tracker-admin'
    )
    ON CONFLICT (source_id) DO UPDATE SET
        url = EXCLUDED.url, organization_id = EXCLUDED.organization_id,
        organization_name = EXCLUDED.organization_name, sector = EXCLUDED.sector, enabled = EXCLUDED.enabled;
END;
$$;

CREATE OR REPLACE FUNCTION ta_admin_source_enable(p_token TEXT, p_id TEXT, p_enabled BOOLEAN) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions
AS $$
BEGIN
    IF NOT _ta_is_admin(p_token) THEN RAISE EXCEPTION 'Not allowed' USING ERRCODE = '42501'; END IF;
    UPDATE admin_sources SET enabled = p_enabled WHERE source_id = p_id;
END;
$$;

CREATE OR REPLACE FUNCTION ta_admin_source_delete(p_token TEXT, p_id TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions
AS $$
BEGIN
    IF NOT _ta_is_admin(p_token) THEN RAISE EXCEPTION 'Not allowed' USING ERRCODE = '42501'; END IF;
    DELETE FROM admin_sources WHERE source_id = p_id;
END;
$$;

REVOKE ALL ON FUNCTION ta_admin_check(TEXT), ta_admin_data(TEXT), ta_admin_source_add(TEXT, JSONB),
    ta_admin_source_upsert(TEXT, JSONB), ta_admin_source_enable(TEXT, TEXT, BOOLEAN), ta_admin_source_delete(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ta_admin_check(TEXT), ta_admin_data(TEXT), ta_admin_source_add(TEXT, JSONB),
    ta_admin_source_upsert(TEXT, JSONB), ta_admin_source_enable(TEXT, TEXT, BOOLEAN), ta_admin_source_delete(TEXT, TEXT) TO anon, authenticated;
