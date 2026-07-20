"""
Ingest course data into the knowledge base (Ch. 14: single source of truth).

Usage:
    python -m app.scripts.ingest_courses

What it does:
    1. Reads app/data/courses_seed.json (replace this with your real, centralized
       course data export once available).
    2. Upserts each course into the `courses` table (source of truth for facts).
    3. Builds one retrieval chunk per course (name + level + prerequisites +
       description) and embeds it.
    4. Stores the embedding in `course_chunks` for retrieval.

Safe to re-run: it clears and rebuilds course_chunks each time, so re-running
after an edit to courses_seed.json keeps embeddings in sync with source facts.
"""

import json
import os
from pathlib import Path

import psycopg
import voyageai
from dotenv import load_dotenv

load_dotenv()

DATA_PATH = Path(__file__).parent.parent / "data" / "courses_seed.json"
DATABASE_URL = os.environ["DATABASE_URL"]
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]

EMBED_MODEL = "voyage-3"  # swap for whatever embedding model you settle on


def build_chunk_text(course: dict) -> str:
    """Turn one course record into a single retrieval-friendly text chunk."""
    parts = [
        f"Naam: {course['name']}",
        f"Categorie: {course['category']}",
        f"Niveau: {course['level']}",
    ]
    if course.get("prerequisites"):
        parts.append(f"Vereisten: {course['prerequisites']}")
    parts.append(f"Beschrijving: {course['description']}")
    if course.get("price") is not None:
        parts.append(f"Prijs: {course['price']}")
    if course.get("duration"):
        parts.append(f"Duur: {course['duration']}")
    return "\n".join(parts)


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        courses = json.load(f)

    vo = voyageai.Client(api_key=VOYAGE_API_KEY)

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
                    RETURNING id;
                    """,
                    course,
                )
                course_id = cur.fetchone()[0]

                # Clear old chunks for this course, then re-embed fresh
                cur.execute("DELETE FROM course_chunks WHERE course_id = %s;", (course_id,))

                chunk_text = build_chunk_text(course)
                embedding = vo.embed([chunk_text], model=EMBED_MODEL, input_type="document").embeddings[0]

                cur.execute(
                    """
                    INSERT INTO course_chunks (course_id, chunk_text, embedding)
                    VALUES (%s, %s, %s);
                    """,
                    (course_id, chunk_text, embedding),
                )

                print(f"Ingested: {course['name']}")

        conn.commit()

    print(f"\nDone. Ingested {len(courses)} courses.")


if __name__ == "__main__":
    main()
