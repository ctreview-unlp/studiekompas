#!/bin/bash
if [ "$SERVICE_ROLE" = "scraper" ]; then
  echo "Running as scraper service"
  python -m app.scripts.scrape_unlp_courses --ingest
else
  echo "Running as web service"
  uvicorn app.main:app --host 0.0.0.0 --port $PORT
fi

chmod +x start.sh