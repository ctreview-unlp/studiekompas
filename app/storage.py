"""
Conversation storage backed by Postgres.

Each session_id maps to exactly one row in `conversations`; the transcript
is stored as a JSONB array of {role, content} objects and grows with each
turn. Consent is recorded separately, since it can happen before any
message has been exchanged.
"""

from pathlib import Path

import psycopg
import psycopg.rows
from psycopg.types.json import Json

from app.retention import lead_months

SCHEMA_PATH = Path(__file__).parent / "db" / "schema.sql"

# A conversation in which the visitor asked at least one question. Opening the
# chat and accepting the data-use notice already creates a row.
HAS_QUESTIONS = "EXISTS (SELECT 1 FROM jsonb_array_elements(c.transcript) t WHERE t->>'role' = 'user')"


def apply_schema(database_url: str) -> None:
    """Run schema.sql, which only adds what's missing, so new columns exist after a deploy."""
    with psycopg.connect(database_url) as conn:
        conn.execute(SCHEMA_PATH.read_text())
        conn.commit()


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


def get_lead_ticket(database_url: str, lead_id: int) -> int | None:
    """The Trengo ticket already opened for this lead, if any."""
    with psycopg.connect(database_url) as conn:
        row = conn.execute("SELECT trengo_ticket_id FROM leads WHERE id = %s;", (lead_id,)).fetchone()
        return row[0] if row else None


def set_lead_ticket(database_url: str, lead_id: int, ticket_id: int) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute("UPDATE leads SET trengo_ticket_id = %s WHERE id = %s;", (ticket_id, lead_id))
        conn.commit()


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
                    topics = %(topics)s,
                    summary_updated_at = now()
                WHERE session_id = %(session_id)s;
                """,
                {
                    "summary": summary.get("summary"),
                    "recommended_course": summary.get("recommended_course"),
                    "recommended_step": summary.get("recommended_step"),
                    "persona_guess": summary.get("persona_guess"),
                    "topics": summary.get("topics"),
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

def list_conversations(database_url: str, only_leads: bool, limit: int, offset: int,
                       include_empty: bool = False) -> list[dict]:
    """
    Consented conversations, newest first, with their lead (if any). Without
    include_empty, only those in which the visitor asked something.
    """
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
                WHERE c.consent_given {"" if include_empty else "AND " + HAS_QUESTIONS}
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
                       c.recommended_step, c.persona_guess, c.topics, c.summary_updated_at,
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


# ---------------------------------------------------------------------
# Usage statistics (app/stats.py): totals only, never conversation content
# ---------------------------------------------------------------------

def usage_stats(database_url: str, days: int | None) -> dict:
    """Counts for conversations started in the last `days` days (all when None)."""
    since = "now() - make_interval(days => %(days)s)" if days else "'-infinity'::timestamptz"
    params = {"days": days}
    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            def rows(sql: str) -> list[dict]:
                cur.execute(sql.replace("{since}", since), params)
                return cur.fetchall()

            totals = rows(f"""
                WITH c AS (
                    SELECT c.*, (SELECT count(*) FROM jsonb_array_elements(c.transcript) t
                                 WHERE t->>'role' = 'user') AS questions
                    FROM conversations c
                    WHERE c.consent_given AND c.started_at >= {{since}}
                )
                SELECT count(*) AS opened,
                       count(*) FILTER (WHERE questions > 0) AS conversations,
                       coalesce(sum(questions), 0) AS questions,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY questions)
                           FILTER (WHERE questions > 0) AS median_questions,
                       (SELECT count(*) FROM leads l JOIN c ON c.id = l.conversation_id) AS leads,
                       count(*) FILTER (WHERE questions > 0 AND topics IS NULL) AS unlabelled,
                       max(started_at) FILTER (WHERE questions > 0) AS last_used,
                       min(started_at) AS first_seen
                FROM c;
            """)[0]
            weekly = rows(f"""
                SELECT date_trunc('week', c.started_at AT TIME ZONE 'Europe/Amsterdam')::date AS week,
                       count(*) FILTER (WHERE {HAS_QUESTIONS}) AS conversations,
                       count(*) AS opened
                FROM conversations c
                WHERE c.consent_given AND c.started_at >= {{since}}
                GROUP BY 1 ORDER BY 1;
            """)
            topics = rows(f"""
                SELECT topic, count(*) AS n
                FROM conversations c, unnest(c.topics) AS topic
                WHERE c.consent_given AND c.started_at >= {{since}} AND {HAS_QUESTIONS}
                GROUP BY 1 ORDER BY 2 DESC;
            """)
            steps = rows(f"""
                SELECT c.recommended_step AS step, count(*) AS n
                FROM conversations c
                WHERE c.consent_given AND c.started_at >= {{since}} AND {HAS_QUESTIONS}
                  AND c.recommended_step IS NOT NULL
                GROUP BY 1 ORDER BY 2 DESC;
            """)
            courses = rows(f"""
                SELECT c.recommended_course AS course, count(*) AS n
                FROM conversations c
                WHERE c.consent_given AND c.started_at >= {{since}} AND {HAS_QUESTIONS}
                  AND coalesce(c.recommended_course, '') <> ''
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
            """)
    return {"totals": totals, "weekly": weekly, "topics": topics, "steps": steps, "courses": courses}


# ---------------------------------------------------------------------
# Topic labelling (app/scripts/label_topics.py)
# ---------------------------------------------------------------------

def conversations_to_label(database_url: str, relabel_all: bool) -> list[dict]:
    """Conversations with questions that have no topics yet (or all of them)."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(f"""
                SELECT c.session_id, c.transcript FROM conversations c
                WHERE c.consent_given AND {HAS_QUESTIONS}
                  {"" if relabel_all else "AND c.topics IS NULL"}
                ORDER BY c.started_at;
            """)
            return cur.fetchall()


def recent_summaries(database_url: str, limit: int) -> list[str]:
    with psycopg.connect(database_url) as conn:
        return [r[0] for r in conn.execute(
            f"""SELECT c.summary FROM conversations c
                WHERE c.summary IS NOT NULL AND {HAS_QUESTIONS}
                ORDER BY c.started_at DESC LIMIT %s;""", (limit,)
        ).fetchall()]
