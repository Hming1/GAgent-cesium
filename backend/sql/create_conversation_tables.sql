-- Conversation history tables for NaLaMap/Gagent-Cesium.
-- Safe to run multiple times in Navicat.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL UNIQUE,
    user_id UUID NULL,
    session_id TEXT NULL,
    title TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    message_count INTEGER NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_pk UUID NOT NULL,
    conversation_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NULL,
    message_type TEXT NULL,
    client_message_id TEXT NULL,
    run_id UUID NULL,
    name TEXT NULL,
    tool_call_id TEXT NULL,
    tool_calls JSONB NULL,
    attachments JSONB NULL,
    extra JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_pk, sequence)
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'users'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_conversations_user_id_users'
    ) THEN
        ALTER TABLE conversations
            ADD CONSTRAINT fk_conversations_user_id_users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_conversation_messages_conversation_pk'
    ) THEN
        ALTER TABLE conversation_messages
            ADD CONSTRAINT fk_conversation_messages_conversation_pk
            FOREIGN KEY (conversation_pk) REFERENCES conversations(id) ON DELETE CASCADE;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'agent_runs'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_conversation_messages_run_id'
    ) THEN
        ALTER TABLE conversation_messages
            ADD CONSTRAINT fk_conversation_messages_run_id
            FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_conversations_conversation_id ON conversations (conversation_id);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_conversations_session_id ON conversations (session_id);
CREATE INDEX IF NOT EXISTS ix_conversations_user_updated ON conversations (user_id, updated_at);
CREATE INDEX IF NOT EXISTS ix_conversations_session_updated ON conversations (session_id, updated_at);

CREATE INDEX IF NOT EXISTS ix_conversation_messages_conversation_pk
    ON conversation_messages (conversation_pk);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_conversation_id
    ON conversation_messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_run_id ON conversation_messages (run_id);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_conv_sequence
    ON conversation_messages (conversation_id, sequence);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_created
    ON conversation_messages (created_at);

COMMIT;
