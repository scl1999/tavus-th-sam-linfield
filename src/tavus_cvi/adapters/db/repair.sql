CREATE TABLE IF NOT EXISTS interview_runtime (
    interview_id UUID PRIMARY KEY REFERENCES interviews(id),
    owner_hash TEXT,
    setup_state TEXT NOT NULL DEFAULT 'ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    connected_at TIMESTAMPTZ,
    remote_end_pending BOOLEAN NOT NULL DEFAULT false,
    revealed_phases JSONB NOT NULL DEFAULT '["intro"]',
    revisions JSONB NOT NULL DEFAULT '{}',
    whiteboards JSONB NOT NULL DEFAULT '{}',
    language TEXT NOT NULL DEFAULT 'python3',
    terminal TEXT NOT NULL DEFAULT ''
);
INSERT INTO interview_runtime(interview_id, created_at, connected_at, revealed_phases, whiteboards)
SELECT id, started_at, started_at,
    CASE current_phase WHEN 'intro' THEN '["intro"]'::jsonb
      WHEN 'coding_easy' THEN '["intro","coding_easy"]'::jsonb
      WHEN 'coding_medium' THEN '["intro","coding_easy","coding_medium"]'::jsonb
      ELSE '["intro","coding_easy","coding_medium","system_design"]'::jsonb END,
    CASE WHEN final_drawio_xml IS NULL THEN '{}'::jsonb
      ELSE jsonb_build_object(COALESCE(system_design_id::text,'unassigned'),final_drawio_xml) END
FROM interviews ON CONFLICT DO NOTHING;
CREATE UNIQUE INDEX IF NOT EXISTS runtime_owner ON interview_runtime(owner_hash)
    WHERE owner_hash IS NOT NULL;
ALTER TABLE interview_runtime ADD COLUMN IF NOT EXISTS checkpoint_request TEXT;
ALTER TABLE interview_runtime ADD COLUMN IF NOT EXISTS checkpoint_ack TEXT;
CREATE TABLE IF NOT EXISTS interview_phase_openings (
    interview_id UUID NOT NULL REFERENCES interviews(id),
    phase TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (interview_id, phase)
);
INSERT INTO interview_phase_openings(interview_id,phase,opened_at)
SELECT interview_id,jsonb_array_elements_text(revealed_phases),created_at
FROM interview_runtime ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS model_card_delivery (
    version INTEGER PRIMARY KEY REFERENCES agent_model_cards(version),
    binding_hash TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tool_invocations (
    conversation_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    interview_id UUID NOT NULL REFERENCES interviews(id),
    request_hash TEXT NOT NULL,
    result JSONB NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, tool_call_id)
);
CREATE TABLE IF NOT EXISTS recording_segments (
    id UUID PRIMARY KEY,
    interview_id UUID NOT NULL REFERENCES interviews(id),
    mime_type TEXT NOT NULL,
    next_sequence INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    path TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS recording_chunks (
    segment_id UUID NOT NULL REFERENCES recording_segments(id),
    sequence INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    payload BYTEA NOT NULL,
    PRIMARY KEY(segment_id, sequence)
);
CREATE TABLE IF NOT EXISTS transcript_event_receipts (
    interview_id UUID NOT NULL REFERENCES interviews(id),
    event_id UUID NOT NULL,
    request_hash TEXT NOT NULL,
    PRIMARY KEY(interview_id,event_id)
);
ALTER TABLE interview_runtime ADD COLUMN IF NOT EXISTS completion_requested BOOLEAN NOT NULL DEFAULT false;
