CREATE TABLE IF NOT EXISTS agent_model_cards (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    agent_name TEXT NOT NULL,
    yaml_path TEXT NOT NULL,
    yaml_sha256 TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL,
    pipeline_mode TEXT NOT NULL,
    face_id TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    perception_model TEXT NOT NULL,
    turn_detection_model TEXT NOT NULL,
    system_instructions TEXT NOT NULL,
    context_template TEXT NOT NULL,
    hardcoded_reminder_template TEXT NOT NULL,
    guardrails_config JSONB NOT NULL,
    tools_config JSONB NOT NULL,
    max_concurrent_tool_calls INTEGER NOT NULL,
    max_context_tokens INTEGER NOT NULL DEFAULT 5000 CHECK (max_context_tokens <= 5000),
    temperature NUMERIC,
    top_p NUMERIC,
    tavus_pal_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leetcode_tests (
    id SERIAL PRIMARY KEY,
    challenge_number INTEGER NOT NULL UNIQUE,
    title_slug TEXT NOT NULL UNIQUE,
    question_title TEXT NOT NULL,
    question TEXT NOT NULL,
    difficulty_level TEXT NOT NULL CHECK (difficulty_level IN ('Easy', 'Medium', 'Hard')),
    hints JSONB NOT NULL DEFAULT '[]',
    boilerplate_code JSONB NOT NULL,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_design_questions (
    id SERIAL PRIMARY KEY,
    question_number INTEGER NOT NULL UNIQUE,
    question_title TEXT NOT NULL,
    problem_statement TEXT NOT NULL,
    functional_requirements JSONB NOT NULL,
    non_functional_requirements JSONB NOT NULL,
    evaluation_rubric JSONB NOT NULL,
    initial_drawio_xml TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    target_role TEXT NOT NULL,
    cv_path TEXT,
    code_submissions JSONB NOT NULL DEFAULT '{}',
    whiteboards JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS interviews (
    id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES candidates(id),
    agent_model_card_version INTEGER NOT NULL REFERENCES agent_model_cards(version),
    tavus_conversation_id TEXT,
    tavus_conversation_url TEXT,
    easy_leetcode_id INTEGER REFERENCES leetcode_tests(id),
    medium_leetcode_id INTEGER REFERENCES leetcode_tests(id),
    system_design_id INTEGER REFERENCES system_design_questions(id),
    current_phase TEXT NOT NULL CHECK (
        current_phase IN (
            'intro', 'coding_easy', 'coding_medium', 'system_design',
            'completed', 'terminated_rude', 'candidate_left'
        )
    ),
    revisiting BOOLEAN NOT NULL DEFAULT FALSE,
    transcript JSONB NOT NULL DEFAULT '[]',
    video_recording_path TEXT,
    final_code_submissions JSONB NOT NULL DEFAULT '{}',
    final_drawio_xml TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

ALTER TABLE interviews ADD COLUMN IF NOT EXISTS revisiting BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS interview_turns (
    id BIGSERIAL PRIMARY KEY,
    interview_id UUID NOT NULL REFERENCES interviews(id),
    turn_idx INTEGER NOT NULL,
    inference_id TEXT,
    role TEXT NOT NULL,
    utterance_text TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    thinking_tokens INTEGER,
    tool_calls JSONB NOT NULL DEFAULT '[]',
    active_concurrent_tools INTEGER NOT NULL DEFAULT 0,
    event_timestamp TIMESTAMPTZ NOT NULL,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS interview_turns_interview_id_idx
    ON interview_turns (interview_id, turn_idx);

CREATE TABLE IF NOT EXISTS tool_call_logs (
    id BIGSERIAL PRIMARY KEY,
    interview_id UUID NOT NULL REFERENCES interviews(id),
    turn_idx INTEGER,
    tool_name TEXT NOT NULL,
    tool_origin TEXT NOT NULL CHECK (tool_origin IN ('system', 'llm', 'perception')),
    arguments JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('executed', 'rejected_concurrency_limit', 'failed')),
    concurrency_at_call INTEGER NOT NULL,
    called_at TIMESTAMPTZ NOT NULL
);

INSERT INTO system_design_questions (
    question_number, question_title, problem_statement,
    functional_requirements, non_functional_requirements, evaluation_rubric, initial_drawio_xml
) VALUES
(
    1,
    'Design a URL shortener',
    'Design a service that turns long URLs into short links and redirects callers to the original URL.',
    '["Create a short link", "Resolve a short link", "Optional custom alias", "Expiration"]'::jsonb,
    '["Read-heavy traffic", "Low redirect latency", "Unique short codes"]'::jsonb,
    '["API shape", "ID generation", "Storage", "Caching", "Failure modes"]'::jsonb,
    NULL
),
(
    2,
    'Design a news feed',
    'Design a home feed that shows recent posts from accounts a person follows.',
    '["Publish a post", "Follow an account", "Read a paginated feed"]'::jsonb,
    '["Fan-out choice", "Freshness", "Hot-key accounts"]'::jsonb,
    '["Write path", "Read path", "Ranking", "Storage", "Scale"]'::jsonb,
    NULL
),
(
    3,
    'Design a rate limiter',
    'Design a rate limiter that protects an API from a single caller exceeding an allowed request rate.',
    '["Allow or deny a request", "Per-key limits", "Return retry guidance"]'::jsonb,
    '["Low added latency", "Correctness across instances", "Burst handling"]'::jsonb,
    '["Algorithm", "Shared state", "Failure behavior", "Client contract"]'::jsonb,
    NULL
)
ON CONFLICT (question_number) DO NOTHING;
