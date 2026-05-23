"""
bot.py — AI Memory Bot (Professional Edition)

Features
────────
• AES-256 encrypted memory storage
• Async SQLite (aiosqlite)
• Inline keyboard menus + pagination
• Owner-only guard via decorator
• /save  /get  /category  /all  /delete
• /media  /viewmedia  /deletemedia
• /stats  /backup  /export
• Auto-save for photo / video / document / voice
• Structured logging to console + file
• Global error handler — no silent crashes
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from functools import wraps
from typing import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    BACKUP_DIR,
    BOT_TOKEN,
    DATA_DIR,
    ITEMS_PER_PAGE,
    LOG_DIR,
    MAX_MSG_LEN,
    OWNER_ID,
)
from crypto import crypto
from database import db

# ── Logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{LOG_DIR}/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MEDIA_ICONS: dict[str, str] = {
    "photo":    "🖼",
    "video":    "🎥",
    "document": "📄",
    "voice":    "🎙",
}

# ── Owner guard ───────────────────────────────────────────────────────────────

def owner_only(func: Callable) -> Callable:
    """Silently ignore any message or callback not from the owner."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = (
            update.effective_user.id
            if update.effective_user
            else None
        )
        if uid != OWNER_ID:
            logger.warning("Unauthorised access attempt from user_id=%s", uid)
            return
        return await func(update, ctx)
    return wrapper

# ── Keyboard builders ─────────────────────────────────────────────────────────

def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 All Memories", callback_data="nav:all:0"),
            InlineKeyboardButton("📂 Media",         callback_data="nav:media:0"),
        ],
        [
            InlineKeyboardButton("📊 Stats",  callback_data="nav:stats"),
            InlineKeyboardButton("💾 Backup", callback_data="nav:backup"),
        ],
        [InlineKeyboardButton("📖 Help", callback_data="nav:help")],
    ])


def kb_pagination(cmd: str, page: int, total: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"nav:{cmd}:{page - 1}"))
    if (page + 1) * ITEMS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"nav:{cmd}:{page + 1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="nav:home")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_delete(kind: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm Delete", callback_data=f"del:{kind}:{item_id}"),
        InlineKeyboardButton("❌ Cancel",          callback_data="nav:home"),
    ]])

# ── Formatters ────────────────────────────────────────────────────────────────

def fmt_memory(row: tuple, decrypted: str) -> str:
    rid, category, _, ts = row
    return (
        f"┌─ *#{rid}*  📁 `{category}`\n"
        f"│  {decrypted}\n"
        f"└─ 🕒 _{ts}_"
    )


def fmt_media_item(row: tuple) -> str:
    rid, mtype, caption, ts = row
    icon = MEDIA_ICONS.get(mtype, "📎")
    cap  = caption or "—"
    return f"{icon} *#{rid}*  `{mtype}`\n  _{cap}_\n  🕒 _{ts}_"


def chunk(text: str, size: int = MAX_MSG_LEN) -> list[str]:
    """Split long text into sendable chunks."""
    return [text[i : i + size] for i in range(0, len(text), size)]

# ── Shared page renderers (used by commands AND callbacks) ────────────────────

async def render_memories_page(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    page: int,
    edit: bool = False,
) -> None:
    total = await db.count_memories()
    target_msg = (
        update.callback_query.message if edit else None
    ) or update.message

    if total == 0:
        await target_msg.reply_text("📭 No memories stored yet.  Use `/save category text` to add one.", parse_mode=ParseMode.MARKDOWN)
        return

    rows = await db.fetch_memories(limit=ITEMS_PER_PAGE, offset=page * ITEMS_PER_PAGE)
    parts: list[str] = []
    for row in rows:
        try:
            dec = crypto.decrypt(row[2])
        except Exception:
            dec = "⚠️ _decryption error_"
        parts.append(fmt_memory(row, dec))

    pages_total = -(-total // ITEMS_PER_PAGE)  # ceiling division
    header = f"📋 *Memories*  •  Page {page + 1}/{pages_total}  •  Total: {total}\n\n"
    body   = "\n\n".join(parts)
    kb     = kb_pagination("all", page, total)

    if edit:
        await target_msg.edit_text(header + body, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await target_msg.reply_text(header + body, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def render_media_page(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    page: int,
    edit: bool = False,
) -> None:
    total = await db.count_media()
    target_msg = (
        update.callback_query.message if edit else None
    ) or update.message

    if total == 0:
        await target_msg.reply_text("📭 No media stored yet.  Send any photo, video, document, or voice note to save it.")
        return

    rows = await db.fetch_media(limit=ITEMS_PER_PAGE, offset=page * ITEMS_PER_PAGE)
    parts = [fmt_media_item(r) for r in rows]

    pages_total = -(-total // ITEMS_PER_PAGE)
    header = f"📂 *Media*  •  Page {page + 1}/{pages_total}  •  Total: {total}\n\n"
    body   = "\n\n".join(parts)

    # Per-item delete buttons
    item_rows = [
        [
            InlineKeyboardButton(
                f"{MEDIA_ICONS.get(r[1], '📎')} #{r[0]} — {r[2] or r[1]}",
                callback_data=f"view:media:{r[0]}",
            ),
            InlineKeyboardButton("🗑 Delete", callback_data=f"ask:media:{r[0]}"),
        ]
        for r in rows
    ]

    # Pagination nav
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"nav:media:{page - 1}"))
    if (page + 1) * ITEMS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"nav:media:{page + 1}"))

    kb_rows = item_rows
    if nav:
        kb_rows = kb_rows + [nav]
    kb_rows = kb_rows + [[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]
    kb = InlineKeyboardMarkup(kb_rows)

    if edit:
        await target_msg.edit_text(header + body, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await target_msg.reply_text(header + body, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ── Command handlers ──────────────────────────────────────────────────────────

@owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔐 *AI Memory Bot*\n\n"
        "Your private, encrypted memory vault.\n"
        "Every entry is secured with *AES-256 encryption*.\n\n"
        "Use the menu below or type /help for all commands.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main_menu(),
    )


@owner_only
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Command Reference*\n\n"
        "*── Memories ──*\n"
        "`/save <category> <text>` — Save encrypted memory\n"
        "`/get <keyword>` — Full-text search\n"
        "`/category <name>` — Filter by category\n"
        "`/all` — Browse all memories (paginated)\n"
        "`/delete <id>` — Delete a memory\n\n"
        "*── Media ──*\n"
        "_Send any photo / video / document / voice_ to auto-save\n"
        "`/media` — Browse saved media\n"
        "`/viewmedia <id>` — Retrieve media by ID\n"
        "`/deletemedia <id>` — Delete media\n\n"
        "*── System ──*\n"
        "`/stats` — Storage statistics\n"
        "`/backup` — Download full database backup\n"
        "`/export` — Export all memories as a text file\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage:* `/save <category> <text>`\n"
            "Example: `/save idea Build an AI SaaS`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    category  = ctx.args[0]
    plaintext = " ".join(ctx.args[1:])
    encrypted = crypto.encrypt(plaintext)
    row_id    = await db.add_memory(category, encrypted)

    logger.info("Memory saved id=%d category=%s", row_id, category)
    await update.message.reply_text(
        f"✅ *Memory saved!*\n\n📁 Category: `{category}`\n🆔 ID: `{row_id}`",
        parse_mode=ParseMode.MARKDOWN,
    )


@owner_only
async def cmd_get(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/get <keyword>`", parse_mode=ParseMode.MARKDOWN)
        return

    keyword = " ".join(ctx.args).lower()
    rows    = await db.fetch_memories()
    matches: list[str] = []

    for row in rows:
        try:
            dec = crypto.decrypt(row[2])
        except Exception:
            continue
        if keyword in dec.lower() or keyword in row[1].lower():
            matches.append(fmt_memory(row, dec))

    if not matches:
        await update.message.reply_text(f"🔍 No results for *{keyword}*.", parse_mode=ParseMode.MARKDOWN)
        return

    header = f"🔍 *Search:* `{keyword}` — {len(matches)} result(s)\n\n"
    for part in chunk(header + "\n\n".join(matches)):
        await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/category <name>`", parse_mode=ParseMode.MARKDOWN)
        return

    cat  = " ".join(ctx.args)
    rows = await db.fetch_memories(category=cat)

    if not rows:
        await update.message.reply_text(f"📂 No memories in category *{cat}*.", parse_mode=ParseMode.MARKDOWN)
        return

    parts: list[str] = []
    for row in rows:
        try:
            dec = crypto.decrypt(row[2])
        except Exception:
            dec = "⚠️ _decryption error_"
        parts.append(fmt_memory(row, dec))

    header = f"📂 *Category:* `{cat}` — {len(parts)} item(s)\n\n"
    for part in chunk(header + "\n\n".join(parts)):
        await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await render_memories_page(update, ctx, page=0)


@owner_only
async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: `/delete <id>`", parse_mode=ParseMode.MARKDOWN)
        return

    mid = int(ctx.args[0])
    await update.message.reply_text(
        f"⚠️ Delete memory *#{mid}*?  This cannot be undone.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_confirm_delete("memory", mid),
    )


@owner_only
async def cmd_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await render_media_page(update, ctx, page=0)


@owner_only
async def cmd_viewmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: `/viewmedia <id>`", parse_mode=ParseMode.MARKDOWN)
        return

    row = await db.get_media(int(ctx.args[0]))
    if not row:
        await update.message.reply_text("❌ Media not found.")
        return

    mtype, file_id, caption = row
    cap = caption or ""
    send = {
        "photo":    update.message.reply_photo,
        "video":    update.message.reply_video,
        "document": update.message.reply_document,
        "voice":    update.message.reply_voice,
    }.get(mtype)

    if send:
        await send(**{mtype: file_id}, caption=cap)
    else:
        await update.message.reply_text("⚠️ Unknown media type.")


@owner_only
async def cmd_deletemedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: `/deletemedia <id>`", parse_mode=ParseMode.MARKDOWN)
        return

    mid = int(ctx.args[0])
    await update.message.reply_text(
        f"⚠️ Delete media *#{mid}*?  This cannot be undone.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_confirm_delete("media", mid),
    )


@owner_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await db.stats()
    await update.message.reply_text(
        "📊 *Storage Statistics*\n\n"
        f"📝 Memories  :  `{s['memories']}`\n"
        f"📁 Categories :  `{s['categories']}`\n"
        f"📂 Media files:  `{s['media']}`",
        parse_mode=ParseMode.MARKDOWN,
    )


@owner_only
async def cmd_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Export all data as a readable text dump (PostgreSQL — no local file)."""
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    lines = [f"AI Memory Bot — Full Backup ({ts})", "=" * 50, ""]

    # Memories
    lines += ["=== MEMORIES ===", ""]
    mem_rows = await db.fetch_memories()
    for row in mem_rows:
        try:
            dec = crypto.decrypt(row[2])
        except Exception:
            dec = "[decryption error]"
        lines += [
            f"ID       : {row[0]}",
            f"Category : {row[1]}",
            f"Text     : {dec}",
            f"Date     : {row[3]}",
            "-" * 40,
            "",
        ]

    # Media
    lines += ["=== MEDIA ===", ""]
    med_rows = await db.fetch_media()
    for row in med_rows:
        lines += [
            f"ID        : {row[0]}",
            f"Type      : {row[1]}",
            f"Caption   : {row[2] or '—'}",
            f"Date      : {row[3]}",
            "-" * 40,
            "",
        ]

    content = "\n".join(lines).encode("utf-8")
    logger.info("Backup exported at %s", ts)
    await update.message.reply_document(
        document=io.BytesIO(content),
        filename=f"backup_{ts}.txt",
        caption=f"💾 Full data backup — {ts}",
    )


@owner_only
async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows = await db.fetch_memories()
    if not rows:
        await update.message.reply_text("📭 No memories to export.")
        return

    lines: list[str] = ["AI Memory Bot — Full Export", "=" * 40, ""]
    for row in rows:
        try:
            dec = crypto.decrypt(row[2])
        except Exception:
            dec = "[decryption error]"
        lines += [
            f"ID       : {row[0]}",
            f"Category : {row[1]}",
            f"Text     : {dec}",
            f"Date     : {row[3]}",
            "-" * 40,
            "",
        ]

    content = "\n".join(lines).encode("utf-8")
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    await update.message.reply_document(
        document=io.BytesIO(content),
        filename=f"memories_export_{ts}.txt",
        caption="📤 Full memory export",
    )

# ── Media auto-save handlers ──────────────────────────────────────────────────

@owner_only
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    photo   = update.message.photo[-1]
    caption = update.message.caption or ""
    rid     = await db.add_media("photo", photo.file_id, caption)
    await update.message.reply_text(f"🖼 Photo saved!  ID: `{rid}`", parse_mode=ParseMode.MARKDOWN)


@owner_only
async def on_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    caption = update.message.caption or ""
    rid     = await db.add_media("video", update.message.video.file_id, caption)
    await update.message.reply_text(f"🎥 Video saved!  ID: `{rid}`", parse_mode=ParseMode.MARKDOWN)


@owner_only
async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    caption = update.message.caption or ""
    rid     = await db.add_media("document", update.message.document.file_id, caption)
    await update.message.reply_text(f"📄 Document saved!  ID: `{rid}`", parse_mode=ParseMode.MARKDOWN)


@owner_only
async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rid = await db.add_media("voice", update.message.voice.file_id)
    await update.message.reply_text(f"🎙 Voice note saved!  ID: `{rid}`", parse_mode=ParseMode.MARKDOWN)

# ── Callback query router ─────────────────────────────────────────────────────

@owner_only
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data  = query.data or ""

    # ── Navigation ────────────────────────────────────────────────────────────
    if data == "nav:home":
        await query.message.edit_text(
            "🔐 *AI Memory Bot* — Main Menu",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main_menu(),
        )

    elif data == "nav:help":
        await query.message.edit_text(
            "📖 *Command Reference*\n\n"
            "`/save <cat> <text>` · `/get <kw>` · `/category <name>`\n"
            "`/all` · `/delete <id>` · `/media` · `/viewmedia <id>`\n"
            "`/deletemedia <id>` · `/stats` · `/backup` · `/export`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Home", callback_data="nav:home")
            ]]),
        )

    elif data == "nav:stats":
        s = await db.stats()
        await query.message.edit_text(
            "📊 *Storage Statistics*\n\n"
            f"📝 Memories  :  `{s['memories']}`\n"
            f"📁 Categories :  `{s['categories']}`\n"
            f"📂 Media files:  `{s['media']}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Home", callback_data="nav:home")
            ]]),
        )

    elif data == "nav:backup":
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        lines = [f"AI Memory Bot — Full Backup ({ts})", "=" * 50, ""]
        lines += ["=== MEMORIES ===", ""]
        for row in await db.fetch_memories():
            try:
                dec = crypto.decrypt(row[2])
            except Exception:
                dec = "[decryption error]"
            lines += [
                f"ID       : {row[0]}",
                f"Category : {row[1]}",
                f"Text     : {dec}",
                f"Date     : {row[3]}",
                "-" * 40, "",
            ]
        lines += ["=== MEDIA ===", ""]
        for row in await db.fetch_media():
            lines += [
                f"ID      : {row[0]}",
                f"Type    : {row[1]}",
                f"Caption : {row[2] or '—'}",
                f"Date    : {row[3]}",
                "-" * 40, "",
            ]
        content = "\n".join(lines).encode("utf-8")
        await query.message.reply_document(
            document=io.BytesIO(content),
            filename=f"backup_{ts}.txt",
            caption=f"💾 Full data backup — {ts}",
        )

    elif data.startswith("nav:all:"):
        page = int(data.split(":")[-1])
        await render_memories_page(update, ctx, page=page, edit=True)

    elif data.startswith("nav:media:"):
        page = int(data.split(":")[-1])
        await render_media_page(update, ctx, page=page, edit=True)

    # ── View media inline ─────────────────────────────────────────────────────
    elif data.startswith("view:media:"):
        mid = int(data.split(":")[-1])
        row = await db.get_media(mid)
        if not row:
            await query.message.reply_text("❌ Media not found.")
            return
        mtype, file_id, caption = row
        cap  = caption or ""
        send = {
            "photo":    query.message.reply_photo,
            "video":    query.message.reply_video,
            "document": query.message.reply_document,
            "voice":    query.message.reply_voice,
        }.get(mtype)
        if send:
            await send(**{mtype: file_id}, caption=cap)
        else:
            await query.message.reply_text("⚠️ Unknown media type.")

    # ── Delete confirmation prompt ─────────────────────────────────────────────
    elif data.startswith("ask:media:"):
        mid = int(data.split(":")[-1])
        await query.message.reply_text(
            f"⚠️ Delete media *#{mid}*?  This cannot be undone.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_confirm_delete("media", mid),
        )

    # ── Delete confirmations ──────────────────────────────────────────────────
    elif data.startswith("del:memory:"):
        mid = int(data.split(":")[-1])
        ok  = await db.delete_memory(mid)
        text = f"🗑 Memory *#{mid}* deleted." if ok else f"❌ Memory *#{mid}* not found."
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Home", callback_data="nav:home")
            ]]),
        )

    elif data.startswith("del:media:"):
        mid = int(data.split(":")[-1])
        ok  = await db.delete_media(mid)
        text = f"🗑 Media *#{mid}* deleted." if ok else f"❌ Media *#{mid}* not found."
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Home", callback_data="nav:home")
            ]]),
        )

# ── Global error handler ──────────────────────────────────────────────────────

async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception for update %s", update, exc_info=ctx.error)

# ── App bootstrap ─────────────────────────────────────────────────────────────

async def post_init(app) -> None:
    await db.initialize()
    logger.info("Bot started — owner_id=%d", OWNER_ID)


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("save",        cmd_save))
    app.add_handler(CommandHandler("get",         cmd_get))
    app.add_handler(CommandHandler("category",    cmd_category))
    app.add_handler(CommandHandler("all",         cmd_all))
    app.add_handler(CommandHandler("delete",      cmd_delete))
    app.add_handler(CommandHandler("media",       cmd_media))
    app.add_handler(CommandHandler("viewmedia",   cmd_viewmedia))
    app.add_handler(CommandHandler("deletemedia", cmd_deletemedia))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("backup",      cmd_backup))
    app.add_handler(CommandHandler("export",      cmd_export))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    # Auto-save media
    app.add_handler(MessageHandler(filters.PHOTO,        on_photo))
    app.add_handler(MessageHandler(filters.VIDEO,        on_video))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.VOICE,        on_voice))

    # Global error handler
    app.add_error_handler(on_error)

    logger.info("🚀  AI Memory Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()