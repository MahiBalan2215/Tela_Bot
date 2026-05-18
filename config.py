"""
config.py — Central configuration for AI Memory Bot.
All paths, tokens, and tunables are defined here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
OWNER_ID: int  = int(os.getenv("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")
if not OWNER_ID:
    raise ValueError("OWNER_ID is not set in .env")

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR   = "data"
DB_PATH    = f"{DATA_DIR}/database.db"
KEY_PATH   = f"{DATA_DIR}/secret.key"
BACKUP_DIR = f"{DATA_DIR}/backups"
LOG_DIR    = "logs"

# ── Bot behaviour ─────────────────────────────────────────────────────────────
ITEMS_PER_PAGE    = 5
MAX_MSG_LEN       = 4096
