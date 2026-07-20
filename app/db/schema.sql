-- Studiekompas — Phase 1 schema
-- Run this once against a fresh Postgres database that has the pgvector extension available.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------
-- Knowledge base (Ch. 14: single source of truth for course facts)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS courses (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    category        TEXT NOT NULL,          -- e.g. 'NLP', 'Systemisch', 'Coaching'
    level           TEXT NOT NULL,          -- e.g. 'Beginner', 'Gevorderd'
    prerequisites   TEXT,                   -- free text description of required prior experience
    description     TEXT NOT NULL,
    price           NUMERIC(10,2),
    duration        TEXT,                   -- e.g. '6 maanden', '3 dagen'
    next_start_date DATE,
    url             TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chunked + embedded representation of the above, used for retrieval.
-- Kept separate from `courses` so re-embedding never risks touching source facts.
CREATE TABLE IF NOT EXISTS course_chunks (
    id          SERIAL PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    chunk_text  TEXT NOT NULL,
    embedding   vector(1024),   -- adjust dimension to match your embedding model
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS course_chunks_embedding_idx
    ON course_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ---------------------------------------------------------------------
-- Conversations (Ch. 18: saved for advisors; Ch. 22: DoD requires this)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id                  SERIAL PRIMARY KEY,
    session_id          UUID NOT NULL DEFAULT gen_random_uuid(),
    persona_guess       TEXT,               -- soft classifier output, not a hard bucket
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at            TIMESTAMPTZ,
    transcript          JSONB NOT NULL DEFAULT '[]'::jsonb,   -- array of {role, content, ts}
    summary             TEXT,
    recommended_course  TEXT,
    recommended_step    TEXT,               -- enroll / info_evening / advice_call / brochure / human_handoff
    naturalness_rating  SMALLINT,           -- 1-5, filled in by tester/visitor feedback (Ch. 22 DoD)
    consent_given       BOOLEAN NOT NULL DEFAULT false,
    consent_timestamp   TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- Leads (Ch. 18: name, email, motivation, objections, etc.)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    name            TEXT,
    email           TEXT,
    course_interest TEXT,
    motivation      TEXT,
    objections      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    retention_until DATE            -- enforce GDPR retention window (Ch. 18 addendum)
);
