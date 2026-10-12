-- ============================================================================
-- Reliable hourly triggers (Supabase starts the GitHub runs; GitHub's own cron drops most of them)
--
-- In the last days GitHub ran the "hourly" monitor only about 3 times a day, up to 9 hours apart.
-- This schedule calls the run-monitor Edge Function, which starts the workflow on GitHub (and does
-- nothing if a run is already queued or in progress). The function accepts the call only with the
-- secret below (function secret CRON_SECRET must have the same value).
--
-- Times are UTC (pg_cron): Dhaka = UTC + 6.
--   monitor : 08:05-20:05 Dhaka hourly, and 00:05 Dhaka
--   epaper  : 07:35 and 11:35 Dhaka (the second one retries papers that failed)
--
-- Before running: 1) replace PASTE_THE_SECRET_HERE (it appears twice in the DO block)
--                 2) add the same value as the Edge Function secret CRON_SECRET
--                 3) redeploy the run-monitor function (it must know CRON_SECRET)
-- Do not commit the real secret.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions;

-- The secret lives in the Vault, not in the job text
DO $$
DECLARE v_id UUID;
BEGIN
    SELECT id INTO v_id FROM vault.secrets WHERE name = 'tender_cron_secret';
    IF v_id IS NULL THEN
        PERFORM vault.create_secret('PASTE_THE_SECRET_HERE', 'tender_cron_secret', 'x-cron-secret for the run-monitor function');
    ELSE
        PERFORM vault.update_secret(v_id, 'PASTE_THE_SECRET_HERE');
    END IF;
END $$;

-- Re-running this file replaces the jobs of the same name
SELECT cron.schedule('tender-monitor', '5 2-14,18 * * *', $job$
    SELECT net.http_post(
        url     := 'https://lhlklttxkchknbjplbvn.supabase.co/functions/v1/run-monitor?workflow=monitor',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'x-cron-secret', (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'tender_cron_secret')),
        body    := '{}'::jsonb
    );
$job$);

SELECT cron.schedule('tender-epaper', '35 1,5 * * *', $job$
    SELECT net.http_post(
        url     := 'https://lhlklttxkchknbjplbvn.supabase.co/functions/v1/run-monitor?workflow=epaper',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'x-cron-secret', (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'tender_cron_secret')),
        body    := '{}'::jsonb
    );
$job$);

-- Check later:
--   SELECT jobname, schedule, active FROM cron.job;
--   SELECT jobid, status, return_message, start_time FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;
--   SELECT id, status_code, content FROM net._http_response ORDER BY created DESC LIMIT 10;   -- the function's answers
