"""
Conversation storage backed by Postgres.

Each session_id maps to exactly one row in `conversations`; the transcript
is stored as a JSONB array of {role, content} objects and grows with each
turn. Consent is recorded separately, since it can happen before any
message has been exchanged.
"""

import psycopg
import psycopg.rows
from psycopg.types.json import Json

from app.retention import lead_months


def get_conversation(database_url: str, session_id: str) -> tuple[list[dict], bool]:
    """
    Return (transcript, consent_given) for a session, or ([], False) if the
    session doesn't exist yet. The chat endpoint uses consent_given to refuse
    messages from sessions that never accepted the data-use notice.
    """
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT transcript, consent_given FROM conversations WHERE session_id = %s;",
                (session_id,),
            )
            row = cur.fetchone()
            return (row[0], row[1]) if row else ([], False)


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


def save_lead(database_url: str, session_id: str, lead: dict) -> int:
    """
    Store (or update) the contact details a visitor left in a conversation.
    One lead per conversation: if the visitor corrects their details later
    in the same chat, the existing row is updated instead of duplicated.
    New leads get a retention_until date, after which app/retention.py
    deletes them. Returns the lead id.
    """
    fields = ("name", "email", "phone", "contact_preference",
              "course_interest", "motivation", "objections")
    values = {f: lead.get(f) for f in fields}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM conversations WHERE session_id = %s;", (session_id,))
            row = cur.fetchone()
            conversation_id = row[0] if row else None

            cur.execute("SELECT id FROM leads WHERE conversation_id = %s;", (conversation_id,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE leads SET name = %(name)s, email = %(email)s, phone = %(phone)s,
                        contact_preference = %(contact_preference)s,
                        course_interest = %(course_interest)s, motivation = %(motivation)s,
                        objections = %(objections)s
                    WHERE id = %(id)s RETURNING id;
                    """,
                    {**values, "id": existing[0]},
                )
            else:
                cur.execute(
                    """
                    INSERT INTO leads (conversation_id, name, email, phone, contact_preference,
                                       course_interest, motivation, objections, retention_until)
                    VALUES (%(conversation_id)s, %(name)s, %(email)s, %(phone)s,
                            %(contact_preference)s, %(course_interest)s, %(motivation)s,
                            %(objections)s, current_date + make_interval(months => %(months)s))
                    RETURNING id;
                    """,
                    {**values, "conversation_id": conversation_id, "months": lead_months()},
                )
            lead_id = cur.fetchone()[0]
        conn.commit()
    return lead_id


def save_summary(database_url: str, session_id: str, summary: dict) -> None:
    """Store the advisor-facing summary fields generated for a conversation."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE conversations SET summary = %(summary)s,
                    recommended_course = %(recommended_course)s,
                    recommended_step = %(recommended_step)s,
                    persona_guess = %(persona_guess)s,
                    summary_updated_at = now()
                WHERE session_id = %(session_id)s;
                """,
                {
                    "summary": summary.get("summary"),
                    "recommended_course": summary.get("recommended_course"),
                    "recommended_step": summary.get("recommended_step"),
                    "persona_guess": summary.get("persona_guess"),
                    "session_id": session_id,
                },
            )
        conn.commit()


def get_conversation_id(database_url: str, session_id: str) -> int | None:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE session_id = %s;", (session_id,)
        ).fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------
# Read-only queries for the advisor overview (app/admin.py)
# ---------------------------------------------------------------------

def list_conversations(database_url: str, only_leads: bool, limit: int, offset: int) -> list[dict]:
    """Consented conversations, newest first, with their lead (if any)."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                f"""
                SELECT c.id, c.started_at, c.summary, c.recommended_course,
                       c.recommended_step,
                       (SELECT count(*) FROM jsonb_array_elements(c.transcript) t
                        WHERE t->>'role' = 'user') AS user_messages,
                       l.name AS lead_name, l.email AS lead_email
                FROM conversations c
                {"JOIN" if only_leads else "LEFT JOIN"} leads l ON l.conversation_id = c.id
                WHERE c.consent_given
                ORDER BY c.started_at DESC
                LIMIT %s OFFSET %s;
                """,
                (limit, offset),
            )
            return cur.fetchall()


def get_conversation_detail(database_url: str, conversation_id: int) -> dict | None:
    """One conversation with its full transcript and lead, for the detail page."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT c.id, c.started_at, c.transcript, c.summary, c.recommended_course,
                       c.recommended_step, c.persona_guess, c.summary_updated_at,
                       l.name AS lead_name, l.email AS lead_email, l.phone AS lead_phone,
                       l.contact_preference AS lead_contact_preference,
                       l.course_interest AS lead_course_interest,
                       l.motivation AS lead_motivation, l.objections AS lead_objections,
                       l.created_at AS lead_created_at
                FROM conversations c
                LEFT JOIN leads l ON l.conversation_id = c.id
                WHERE c.id = %s AND c.consent_given;
                """,
                (conversation_id,),
            )
            return cur.fetchone()
