"""
Data retention (GDPR): delete conversations and leads once they're no
longer needed, as promised in the widget's consent notice.

    RETENTION_CONVERSATION_MONTHS  (default 6)   conversations without a lead
    RETENTION_LEAD_MONTHS          (default 12)  leads, and the conversation they came from

A conversation that produced a lead is kept as long as the lead, so the
advisor still has the context while following up. Runs daily as part of
the scraper job (start.sh), via `python -m app.retention`.
"""

import os

import psycopg


def conversation_months() -> int:
    return int(os.environ.get("RETENTION_CONVERSATION_MONTHS", "6"))


def lead_months() -> int:
    return int(os.environ.get("RETENTION_LEAD_MONTHS", "12"))


def purge_expired(conn: psycopg.Connection, conversation_months: int, lead_months: int) -> tuple[int, int]:
    """
    Delete expired leads, then expired conversations without a lead.
    Returns (leads_deleted, conversations_deleted). Does not commit, so
    the caller controls the transaction.
    """
    with conn.cursor() as cur:
        # retention_until is set when a lead is saved; leads from before that
        # existed fall back to their creation date.
        cur.execute(
            """
            DELETE FROM leads
            WHERE COALESCE(retention_until,
                           (created_at + make_interval(months => %s))::date) < current_date;
            """,
            (lead_months,),
        )
        leads_deleted = cur.rowcount

        cur.execute(
            """
            DELETE FROM conversations c
            WHERE c.started_at < now() - make_interval(months => %s)
              AND NOT EXISTS (SELECT 1 FROM leads l WHERE l.conversation_id = c.id);
            """,
            (conversation_months,),
        )
        conversations_deleted = cur.rowcount
    return leads_deleted, conversations_deleted


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        leads, conversations = purge_expired(conn, conversation_months(), lead_months())
        conn.commit()
    print(
        f"Retention: deleted {leads} lead(s) older than {lead_months()} months and "
        f"{conversations} conversation(s) older than {conversation_months()} months."
    )


if __name__ == "__main__":
    main()
