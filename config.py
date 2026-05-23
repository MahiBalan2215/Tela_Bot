"""
config.py — Central configuration for AI Memory Bot.
All paths, tokens, and tunables are defined here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
BOT_TOKEN: str    = os.getenv("BOT_TOKEN", "")
OWNER_ID: int     = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")
if not OWNER_ID:
    raise ValueError("OWNER_ID is not set in .env")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env")

# Railway injects postgres:// but asyncpg needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Paths (kept for log/backup dirs) ──────────────────────────────────────────
DATA_DIR   = "data"
BACKUP_DIR = f"{DATA_DIR}/backups"
LOG_DIR    = "logs"

# ── Bot behaviour ─────────────────────────────────────────────────────────────
ITEMS_PER_PAGE = 5
MAX_MSG_LEN    = 4096
