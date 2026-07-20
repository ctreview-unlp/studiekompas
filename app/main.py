"""
Minimal API skeleton — Day 1 goal: get this deployed and reachable before
building any real logic on top of it.
"""

from fastapi import FastAPI

app = FastAPI(title="Studiekompas API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Studiekompas API is running."}
