"""
Test setup: app.main reads these at import time. Dummy values keep the
tests from ever touching the real database or Claude API — every external
call is replaced with a fake in the tests themselves.
"""

import os

os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:1/test"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
