# Studiekompas

Backend skeleton for UNLP's digital study advisor (Phase 1). This covers the
first steps of the build plan: repo + deploy skeleton, database schema,
course data ingestion, and a bare retrieval test — all *before* any
conversation logic is written.

## Folder structure

```
Studiekompas/
├── app/
│   ├── main.py                 # FastAPI skeleton (health check only, for now)
│   ├── db/
│   │   └── schema.sql          # Postgres + pgvector schema
│   ├── data/
│   │   └── courses_seed.json   # PLACEHOLDER course data — replace with your real export
│   └── scripts/
│       ├── ingest_courses.py   # loads courses_seed.json → embeds → stores in pgvector
│       └── test_retrieval.py   # standalone retrieval smoke test (no LLM involved)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup (Day 1–2)

1. **Create a Postgres database** (Railway/Render both offer this with one click).
   Make sure the `vector` extension is available — most managed providers support it,
   but confirm before you commit to a host.

2. **Copy environment variables:**
   ```bash
   cp .env.example .env
   # then fill in DATABASE_URL, ANTHROPIC_API_KEY, VOYAGE_API_KEY
   # optional: ALLOWED_ORIGINS — comma-separated sites allowed to embed the widget
   #           (defaults to https://unlp.nl,https://www.unlp.nl)
   ```

3. **Install dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Run the schema:**
   ```bash
   psql "$DATABASE_URL" -f app/db/schema.sql
   ```

5. **Run the API locally and confirm it's alive:**
   ```bash
   uvicorn app.main:app --reload
   curl http://localhost:8000/health
   ```

6. **Deploy this skeleton to Railway/Render now**, before adding real logic —
   the point is to prove the deploy pipeline works while the app is still trivial.

## Knowledge base (Day 3–5)

1. **Replace `app/data/courses_seed.json` with your real, centralized course data.**
   The current file only contains a partial placeholder set built from the course
   list in the project brief — prerequisites, prices, durations, and dates are
   mostly blank and need to come from UNLP's actual source.

2. **Ingest it:**
   ```bash
   python -m app.scripts.ingest_courses
   ```
   Safe to re-run any time the source data changes.

3. **Prove retrieval works before writing any conversation logic:**
   ```bash
   python -m app.scripts.test_retrieval "ik wil coach worden, geen ervaring"
   ```
   You should see a ranked list of plausible course matches. If the top
   results look wrong, fix the chunk text or embedding model before moving on —
   don't let a weak retrieval layer become the conversation's problem later.

## What's deliberately NOT here yet

Per the build plan, conversation logic (system prompt, persona classifier,
suitability/boundary handling per Ch. 16) comes *after* retrieval is proven,
not before. Same for the frontend widget, GDPR consent flow, and conversation
storage wiring — those are the next steps once this foundation is solid.

## Reference

See `Studiekompas_Phase1_Buildplan.docx` for the full scope, timeline, and
tech stack this scaffold is built against.
# studiekompas
# studiekompas

## Leads, summaries and the advisor overview

- **Lead capture:** when a visitor wants contact with an advisor, the bot asks
  for their name and email (plus phone for a callback) and stores them in
  `leads` via the `save_lead` tool (`app/leads.py`).
- **Summaries:** after every reply, a background task writes a short summary,
  recommended course, next step and persona guess onto the conversation
  (`app/summarize.py`).
- **Advisor email:** a new lead triggers an email to the advisors (`app/notify.py`).
- **Overview:** advisors read conversations and leads at `/admin` (`app/admin.py`).

Environment variables (set in Railway):

| Variable | Purpose |
|---|---|
| `ADMIN_PASSWORD` | Enables `/admin`; without it the page returns 404 |
| `ADMIN_USERNAME` | Login name for `/admin` (default `unlp`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Mail server for lead emails (port defaults to 587, STARTTLS) |
| `SMTP_FROM` | Sender address (defaults to `SMTP_USERNAME`) |
| `LEAD_NOTIFY_TO` | Comma-separated advisor addresses that receive lead emails |
| `PUBLIC_BASE_URL` | Base URL used for `/admin` links in emails (defaults to the Railway URL) |

Without the SMTP variables, lead emails are skipped (logged) and leads are
still visible in `/admin`.

## Data retention

Every day, the scraper job (`start.sh`, `SERVICE_ROLE=scraper`) first runs
`python -m app.retention`, which deletes:

- conversations without a lead older than `RETENTION_CONVERSATION_MONTHS` (default 6)
- leads older than `RETENTION_LEAD_MONTHS` (default 12), together with their conversation

New leads get `retention_until` set when they're saved. Set `RETENTION_LEAD_MONTHS`
on both the web and scraper services if you change it, so the two agree.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests replace the database and Claude API with fakes, so they need no
credentials and cost nothing to run.
