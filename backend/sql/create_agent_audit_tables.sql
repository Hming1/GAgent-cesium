-- Agent run audit tables for NaLaMap/Gagent-Cesium.
-- Target database: PostgreSQL/PostGIS.
-- This file is safe to run multiple times in Navicat.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NULL,
    session_id TEXT NULL,
    conversation_id TEXT NULL,
    stream_id TEXT NULL,
    endpoint TEXT NOT NULL,
    query TEXT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    audit_level TEXT NOT NULL DEFAULT 'tool',
    model_provider TEXT NULL,
    model_name TEXT NULL,
    input_messages JSONB NULL,
    output_messages JSONB NULL,
    initial_state JSONB NULL,
    final_state JSONB NULL,
    options_snapshot JSONB NULL,
    metrics JSONB NULL,
    error JSONB NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_run_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    name TEXT NULL,
    input JSONB NULL,
    output JSONB NULL,
    payload JSONB NULL,
    input_json JSONB NULL,
    output_json JSONB NULL,
    payload_json JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


ALTER TABLE agent_run_events
    ADD COLUMN IF NOT EXISTS input_json JSONB NULL,
    ADD COLUMN IF NOT EXISTS output_json JSONB NULL,
    ADD COLUMN IF NOT EXISTS payload_json JSONB NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'users'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'agent_runs'
          AND constraint_name = 'fk_agent_runs_user_id_users'
    ) THEN
        ALTER TABLE agent_runs
            ADD CONSTRAINT fk_agent_runs_user_id_users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'agent_run_events'
          AND constraint_name = 'fk_agent_run_events_run_id_agent_runs'
    ) THEN
        ALTER TABLE agent_run_events
            ADD CONSTRAINT fk_agent_run_events_run_id_agent_runs
            FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id
    ON agent_runs (user_id);

CREATE INDEX IF NOT EXISTS ix_agent_runs_session_id
    ON agent_runs (session_id);

CREATE INDEX IF NOT EXISTS ix_agent_runs_conversation_id
    ON agent_runs (conversation_id);

CREATE INDEX IF NOT EXISTS ix_agent_runs_stream_id
    ON agent_runs (stream_id);

CREATE INDEX IF NOT EXISTS ix_agent_runs_session_created
    ON agent_runs (session_id, created_at);

CREATE INDEX IF NOT EXISTS ix_agent_runs_status_created
    ON agent_runs (status, created_at);

CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_id
    ON agent_run_events (run_id);

CREATE INDEX IF NOT EXISTS ix_agent_run_events_event_type
    ON agent_run_events (event_type);

CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_sequence
    ON agent_run_events (run_id, sequence);

CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_type
    ON agent_run_events (run_id, event_type);

COMMIT;
