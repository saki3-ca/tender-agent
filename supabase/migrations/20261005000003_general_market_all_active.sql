-- General Market tab: every tender that is still active (deadline not passed or unknown)
-- or was first seen in the last 7 days.
CREATE OR REPLACE VIEW v_general_market AS
SELECT
    o.id, o.organization_id, o.organization_name, o.organization_type, o.title,
    o.reference_number, o.category, o.outside_ifrs9_target, o.priority, o.score,
    o.fit_type, o.publication_date, o.submission_deadline, o.days_remaining,
    o.source_url, o.document_url, o.lifecycle_status, o.review_status,
    o.ai_confidence, o.first_seen, o.last_checked
FROM opportunities o
WHERE o.pipeline = 'GENERAL_MARKET'
  AND o.record_type = 'OPPORTUNITY'
  AND (
        o.submission_deadline IS NULL
     OR o.submission_deadline >= now()
     OR COALESCE(o.publication_date, o.first_seen) >= now() - interval '7 days'
  )
ORDER BY o.submission_deadline ASC NULLS LAST, o.score DESC;
