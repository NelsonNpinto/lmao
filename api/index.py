"""Vercel entry point: the FastAPI app as one Python function.

Vercel serves the built frontend as static files and rewrites /api/* here, so
the UI and the API share one origin. The function's filesystem is read-only
except /tmp, so the SQLite database lives there and is seeded from the
committed raw Elexon cache (data/raw) on each cold start, in about 2 s.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("ENV", "prod")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/windsight.db")
os.environ.setdefault("SEED_BLOCKING", "true")
os.environ.setdefault("WARM_CACHE", "false")
os.environ.setdefault("GIT_SHA", os.environ.get("VERCEL_GIT_COMMIT_SHA", "vercel")[:7])
# Without a configured token, refresh is effectively disabled (random per instance).
os.environ.setdefault("ADMIN_TOKEN", secrets.token_urlsafe(32))

from app.main import app

__all__ = ["app"]
