"""
Test setup: app.main reads these at import time. Dummy values keep the
tests from ever touching the real database or Claude API — every external
call is replaced with a fake in the tests themselves.
"""

import os

os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:1/test"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
# Empty, so a Trengo token in a local .env never switches on lead capture
# or reaches the real Trengo API (load_dotenv doesn't override set values).
os.environ["TRENGO_API_TOKEN"] = ""
os.environ["TRENGO_CHANNEL_ID"] = ""
os.environ["TRENGO_TEAM_ID"] = ""
