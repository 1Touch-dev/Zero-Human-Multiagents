-- Step 12: Logging/monitoring health queries
-- Run against Dev paperclip DB to inspect per-ticket health.

-- 1) Latest agent run per ticket identifier (last 24h)
SELECT DISTINCT ON (ar.issue_identifier)
    ar.issue_identifier,
    ar.role_key,
    ar.status,
    ar.github_mode,
    ar.duration_ms,
    ar.started_at,
    ar.completed_at
FROM public.agent_runs ar
WHERE ar.started_at >= NOW() - INTERVAL '24 hours'
ORDER BY ar.issue_identifier, ar.started_at DESC;

-- 2) Skill reliability snapshot (last 24h)
SELECT
    sr.skill_name,
    COUNT(*) AS total_runs,
    SUM(CASE WHEN sr.status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_runs,
    SUM(CASE WHEN sr.status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
    ROUND(AVG(sr.duration_ms), 2) AS avg_duration_ms
FROM public.skill_runs sr
WHERE sr.started_at >= NOW() - INTERVAL '24 hours'
GROUP BY sr.skill_name
ORDER BY total_runs DESC, sr.skill_name;

-- 3) Usage metrics by ticket (last 24h)
SELECT
    ar.issue_identifier,
    ul.metric_key,
    ROUND(AVG(ul.metric_value), 2) AS avg_metric_value,
    SUM(ul.metric_value) AS total_metric_value,
    COUNT(*) AS samples
FROM public.usage_logs ul
LEFT JOIN public.agent_runs ar ON ar.id = ul.agent_run_id
WHERE ul.recorded_at >= NOW() - INTERVAL '24 hours'
GROUP BY ar.issue_identifier, ul.metric_key
ORDER BY ar.issue_identifier, ul.metric_key;

-- 4) Potentially unhealthy runs (failed or long-running > 10 min)
SELECT
    ar.issue_identifier,
    ar.role_key,
    ar.status,
    ar.duration_ms,
    ar.error_message,
    ar.started_at
FROM public.agent_runs ar
WHERE ar.started_at >= NOW() - INTERVAL '24 hours'
  AND (
    ar.status = 'failed'
    OR COALESCE(ar.duration_ms, 0) > 600000
  )
ORDER BY ar.started_at DESC;
