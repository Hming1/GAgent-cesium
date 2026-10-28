-- Query one complete agent run timeline in Navicat.
-- Replace the run id below with agent_runs.id.

-- 1) Run summary.
SELECT
    id,
    user_id,
    session_id,
    conversation_id,
    stream_id,
    endpoint,
    query,
    status,
    audit_level,
    model_provider,
    model_name,
    started_at,
    ended_at,
    metrics,
    error
FROM agent_runs
WHERE id = 'eb2dcc98-257d-40d4-9bd8-47a09ca85bc8';

-- 2) Ordered execution events.
SELECT
    sequence,
    event_type,
    name,
    COALESCE(input_json, input) AS input_json,
    COALESCE(output_json, output) AS output_json,
    COALESCE(payload_json, payload) AS payload_json,
    created_at
FROM agent_run_events
WHERE run_id = 'eb2dcc98-257d-40d4-9bd8-47a09ca85bc8'
ORDER BY sequence;

-- 3) One JSON document containing run summary + complete ordered timeline.
SELECT jsonb_pretty(
    jsonb_build_object(
        'run',
        to_jsonb(r),
        'events',
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'sequence', e.sequence,
                    'event_type', e.event_type,
                    'name', e.name,
                    'input_json', COALESCE(e.input_json, e.input),
                    'output_json', COALESCE(e.output_json, e.output),
                    'payload_json', COALESCE(e.payload_json, e.payload),
                    'created_at', e.created_at
                )
                ORDER BY e.sequence
            ) FILTER (WHERE e.id IS NOT NULL),
            '[]'::jsonb
        )
    )
) AS agent_run_timeline
FROM agent_runs r
LEFT JOIN agent_run_events e ON e.run_id = r.id
WHERE r.id = 'eb2dcc98-257d-40d4-9bd8-47a09ca85bc8'
GROUP BY r.id;

-- 4) Recent runs with event counts.
SELECT
    r.id,
    r.query,
    r.status,
    r.endpoint,
    r.audit_level,
    r.model_provider,
    r.model_name,
    r.started_at,
    r.ended_at,
    COUNT(e.id) AS event_count
FROM agent_runs r
LEFT JOIN agent_run_events e ON e.run_id = r.id
GROUP BY r.id
ORDER BY r.created_at DESC
LIMIT 20;
