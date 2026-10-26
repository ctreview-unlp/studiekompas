"""
Ingest course data into the knowledge base (Ch. 14: single source of truth).

Usage:
    python -m app.scripts.ingest_courses

What it does:
    1. Reads app/data/courses_seed.json (replace this with your real, centralized
       course data export once available).
    2. Upserts each course into the `courses` table (source of truth for facts).

Safe to re-run: existing courses are updated in place. The chat reads courses
straight from the database, so no embeddings are needed.
"""

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATA_PATH = Path(__file__).parent.parent / "data" / "courses_seed.json"
DATABASE_URL = os.environ["DATABASE_URL"]


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        courses = json.load(f)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for course in courses:
                # Upsert into `courses` (source of truth)
                cur.execute(
                    """
                    INSERT INTO courses (name, category, level, prerequisites, description,
                                          price, duration, next_start_date, url)
                    VALUES (%(name)s, %(category)s, %(level)s, %(prerequisites)s, %(description)s,
                            %(price)s, %(duration)s, %(next_start_date)s, %(url)s)
                    ON CONFLICT (name) DO UPDATE SET
                        category = EXCLUDED.category,
                        level = EXCLUDED.level,
                        prerequisites = EXCLUDED.prerequisites,
                        description = EXCLUDED.description,
                        price = EXCLUDED.price,
                        duration = EXCLUDED.duration,
                        next_start_date = EXCLUDED.next_start_date,
                        url = EXCLUDED.url,
                        updated_at = now()
                    """,
                    course,
                )

                print(f"Ingested: {course['name']}")

        conn.commit()

    print(f"\nDone. Ingested {len(courses)} courses.")


if __name__ == "__main__":
    main()
