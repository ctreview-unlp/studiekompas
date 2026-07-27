"""
Conversation storage backed by Postgres.

Each session_id maps to exactly one row in `conversations`; the transcript
is stored as a JSONB array of {role, content} objects and grows with each
turn. Consent is recorded separately, since it can happen before any
message has been exchanged.
"""

import psycopg
from psycopg.types.json import Json


def get_transcript(database_url: str, session_id: str) -> list[dict]:
    """Return the existing transcript for a session, or [] if none exists yet."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT transcript FROM conversations WHERE session_id = %s;",
                (session_id,),
            )
            row = cur.fetchone()
            return row[0] if row else []


def save_transcript(database_url: str, session_id: str, transcript: list[dict]) -> None:
    """Upsert the full transcript for a session."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (session_id, transcript)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    transcript = EXCLUDED.transcript;
                """,
                (session_id, Json(transcript)),
            )
        conn.commit()


def record_consent(database_url: str, session_id: str) -> None:
    """Record that a visitor has given consent, before any conversation exists yet."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (session_id, consent_given, consent_timestamp)
                VALUES (%s, true, now())
                ON CONFLICT (session_id) DO UPDATE SET
                    consent_given = true,
                    consent_timestamp = now();
                """,
                (session_id,),
            )
        conn.commit()


def mark_ended(database_url: str, session_id: str) -> None:
    """Optional: call when a conversation is explicitly closed."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET ended_at = now() WHERE session_id = %s;",
                (session_id,),
            )
        conn.commit()