"""
Conversation storage backed by Postgres.

Replaces the in-memory dict that was used for early testing. Each session_id
maps to exactly one row in `conversations`; the transcript is stored as a
JSONB array of {role, content} objects and grows with each turn.
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


def mark_ended(database_url: str, session_id: str) -> None:
    """Optional: call when a conversation is explicitly closed."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET ended_at = now() WHERE session_id = %s;",
                (session_id,),
            )
        conn.commit()