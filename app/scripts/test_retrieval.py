"""
Retrieval smoke test — run this BEFORE writing any conversation logic.

The goal is to prove that given a rough, natural-language query, the knowledge
base returns sensible course matches. No LLM conversation involved yet.

Usage:
    python -m app.scripts.test_retrieval "ik wil coach worden, geen ervaring"
"""

import os
import sys

import psycopg
import voyageai
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
EMBED_MODEL = "voyage-3"
TOP_K = 5


def retrieve(query: str, top_k: int = TOP_K):
    vo = voyageai.Client(api_key=VOYAGE_API_KEY)
    query_embedding = vo.embed([query], model=EMBED_MODEL, input_type="query").embeddings[0]

    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.name, c.level, c.prerequisites, cc.chunk_text,
                       cc.embedding <=> %s AS distance
                FROM course_chunks cc
                JOIN courses c ON c.id = cc.course_id
                ORDER BY distance ASC
                LIMIT %s;
                """,
                (query_embedding, top_k),
            )
            return cur.fetchall()


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "ik wil coach worden, geen ervaring"
    print(f"Query: {query}\n")

    results = retrieve(query)
    for i, (name, level, prereqs, chunk_text, distance) in enumerate(results, start=1):
        print(f"{i}. {name}  (level={level}, distance={distance:.4f})")
        print(f"   prerequisites: {prereqs}")
        print()


if __name__ == "__main__":
    main()
