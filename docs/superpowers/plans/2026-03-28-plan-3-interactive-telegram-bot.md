# Plan 3: Interactive Telegram Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current fire-and-forget Telegram sender with a full interactive bot — inline buttons on every job post, user commands (/subscribe, /search, /saved, /stats), personalized DM alerts, and polling-based architecture.

**Architecture:** `python-telegram-bot` library in async polling mode. The bot runs in the same process as FastAPI (via asyncio). Job messages include inline keyboard buttons (Save, Share, Similar, Not Relevant). Callback queries route through `bot/callbacks.py`. Commands route through `bot/commands.py`. DM alerts are triggered by the job fetcher after enrichment.

**Tech Stack:** Python 3.11, python-telegram-bot>=21.0, FastAPI, asyncio, psycopg2

**Spec:** `docs/superpowers/specs/2026-03-28-v2-redesign-design.md` (Section 3)

**Depends on:** Plan 1 (core/db.py, core/models.py), Plan 2 (core/enrichment.py)
**Blocks:** Plan 6 (integration)

---

## File Structure

```
bot/
├── __init__.py
├── app.py              # Bot application setup, polling start/stop
├── sender.py           # Format + send job messages with inline buttons (replaces telegram_sender.py)
├── callbacks.py        # Inline button handlers (save, share, similar, not_relevant)
├── commands.py         # /subscribe, /unsubscribe, /mysubs, /search, /saved, /stats, /top, /salary, /help
├── notifications.py    # Personalized DM alerts for subscribed users
└── keyboards.py        # Inline keyboard builders (shared across commands and callbacks)
```

---

### Task 1: Bot Application Setup

**Files:**
- Create: `bot/__init__.py`
- Create: `bot/app.py`
- Modify: `requirements.txt` — add `python-telegram-bot>=21.0`

- [ ] **Step 1: Update requirements.txt**

Add `python-telegram-bot>=21.0` to `requirements.txt`.

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 3: Create bot/__init__.py**

```python
# bot/__init__.py
```

- [ ] **Step 4: Write bot/app.py**

```python
# bot/app.py
"""
Telegram bot application setup.
Uses python-telegram-bot in polling mode with asyncio.
"""

import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
)
from core.config import TELEGRAM_BOT_TOKEN

log = logging.getLogger(__name__)

_app: Application | None = None


def get_app() -> Application:
    """Get or create the bot Application singleton."""
    global _app
    if _app is None:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        _register_handlers(_app)
        log.info("Telegram bot application created")
    return _app


def _register_handlers(app: Application) -> None:
    """Register all command and callback handlers."""
    from bot.commands import (
        cmd_start, cmd_help, cmd_subscribe, cmd_unsubscribe,
        cmd_mysubs, cmd_search, cmd_saved, cmd_stats, cmd_top,
        cmd_salary,
    )
    from bot.callbacks import handle_callback

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("mysubs", cmd_mysubs))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("saved", cmd_saved))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("salary", cmd_salary))

    # Callback queries (inline button presses)
    app.add_handler(CallbackQueryHandler(handle_callback))


async def start_polling() -> None:
    """Start the bot in polling mode."""
    app = get_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Bot polling started")


async def stop_polling() -> None:
    """Stop the bot gracefully."""
    if _app and _app.updater:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        log.info("Bot polling stopped")
```

- [ ] **Step 5: Commit**

```bash
git add bot/__init__.py bot/app.py requirements.txt
git commit -m "feat: add bot application setup with polling mode"
```

---

### Task 2: Inline Keyboard Builders

**Files:**
- Create: `bot/keyboards.py`

- [ ] **Step 1: Write bot/keyboards.py**

```python
# bot/keyboards.py
"""
Inline keyboard builders for job messages and interactive commands.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def job_buttons(job_id: int) -> InlineKeyboardMarkup:
    """Build the inline buttons shown under each job message."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Save", callback_data=f"save:{job_id}"),
            InlineKeyboardButton("📤 Share", callback_data=f"share:{job_id}"),
            InlineKeyboardButton("🔍 Similar", callback_data=f"similar:{job_id}"),
            InlineKeyboardButton("👎 Not Relevant", callback_data=f"not_relevant:{job_id}"),
        ]
    ])


def topic_selection_keyboard(selected: set[str] = None) -> InlineKeyboardMarkup:
    """Build topic selection keyboard for /subscribe."""
    selected = selected or set()
    topics = [
        ("backend", "⚙️ Backend"),
        ("frontend", "🎨 Frontend"),
        ("mobile", "📱 Mobile"),
        ("devops", "🚀 DevOps"),
        ("qa", "🧪 QA"),
        ("ai_ml", "🤖 AI/ML"),
        ("cybersecurity", "🔒 Security"),
        ("gamedev", "🎮 Games"),
        ("blockchain", "⛓️ Web3"),
        ("erp", "🏢 ERP"),
        ("internships", "🎓 Internships"),
    ]
    buttons = []
    row = []
    for key, label in topics:
        check = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(
            f"{check}{label}",
            callback_data=f"sub_topic:{key}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✅ Done", callback_data="sub_done")])
    return InlineKeyboardMarkup(buttons)


def seniority_selection_keyboard(selected: set[str] = None) -> InlineKeyboardMarkup:
    """Build seniority selection keyboard for /subscribe."""
    selected = selected or set()
    levels = [
        ("intern", "🎓 Intern"),
        ("junior", "🌱 Junior"),
        ("mid", "💼 Mid"),
        ("senior", "👨‍💻 Senior"),
        ("lead", "⭐ Lead"),
        ("executive", "🏛️ Executive"),
    ]
    buttons = []
    row = []
    for key, label in levels:
        check = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(
            f"{check}{label}",
            callback_data=f"sub_seniority:{key}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✅ Done", callback_data="sub_seniority_done")])
    return InlineKeyboardMarkup(buttons)


def pagination_keyboard(current_page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup:
    """Build prev/next pagination buttons."""
    buttons = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"{prefix}:{current_page - 1}"))
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"{prefix}:{current_page + 1}"))
    if buttons:
        return InlineKeyboardMarkup([buttons])
    return None
```

- [ ] **Step 2: Commit**

```bash
git add bot/keyboards.py
git commit -m "feat: add inline keyboard builders for jobs and subscriptions"
```

---

### Task 3: Job Sender with Inline Buttons

**Files:**
- Create: `bot/sender.py`

- [ ] **Step 1: Write bot/sender.py**

This replaces the old `telegram_sender.py` with inline button support.

```python
# bot/sender.py
"""
Job message formatting and sending with inline buttons.
Replaces the old telegram_sender.py.
"""

import time
import logging
from telegram import Bot
from telegram.error import TelegramError

from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, TELEGRAM_SEND_DELAY
from core.models import Job
from core.channels import CHANNELS, get_topic_thread_id
from core import db
from bot.keyboards import job_buttons

log = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_job_message(job: Job) -> str:
    """Format a job as an HTML Telegram message."""
    emoji = job.emoji
    title = _escape_html(job.title)
    company = _escape_html(job.company) if job.company else "Unknown"
    location = _escape_html(job.location) if job.location else "Not specified"
    source = _escape_html(job.display_source)

    lines = [
        f"{emoji} <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]

    if job.salary_display:
        lines.append(f"💰 {_escape_html(job.salary_display)}")
    if job.seniority and job.seniority != "mid":
        seniority_labels = {
            "intern": "🎓 Intern", "junior": "🌱 Junior",
            "senior": "👨‍💻 Senior", "lead": "⭐ Lead",
            "executive": "🏛️ Executive",
        }
        label = seniority_labels.get(job.seniority, "")
        if label:
            lines.append(label)
    if job.job_type:
        lines.append(f"📋 {_escape_html(job.job_type)}")
    if job.is_remote:
        lines.append("🌍 Remote")

    lines.append("")
    lines.append(f'🔗 <a href="{job.url}">Apply Now</a>')
    lines.append(f"📡 Source: {source}")

    return "\n".join(lines)


async def send_job_to_topics(bot: Bot, job: Job, job_db_id: int) -> dict:
    """
    Send a job to all matching Telegram topics with inline buttons.

    Args:
        bot: Telegram Bot instance
        job: The job to send
        job_db_id: The job's database ID (for button callbacks)

    Returns: {topic_key: {"chat_id": ..., "message_id": ...}} for sent messages
    """
    message = format_job_message(job)
    keyboard = job_buttons(job_db_id)
    sent_messages = {}

    for topic_key in job.topics:
        thread_id = get_topic_thread_id(topic_key)
        if thread_id is None:
            continue

        topic_name = CHANNELS[topic_key]["name"]
        try:
            result = await bot.send_message(
                chat_id=TELEGRAM_GROUP_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
                message_thread_id=thread_id,
                reply_markup=keyboard,
            )
            sent_messages[topic_key] = {
                "chat_id": str(TELEGRAM_GROUP_ID),
                "message_id": result.message_id,
            }
            log.info(f"  ✓ Sent to {topic_name}: {job.title}")
        except TelegramError as e:
            log.error(f"  ✗ Failed {topic_name}: {job.title} — {e}")

        await _async_sleep(0.5)

    return sent_messages


async def send_jobs(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send multiple jobs to their matching topics.

    Args:
        bot: Telegram Bot instance
        jobs: List of (Job, db_id) tuples

    Returns: Total successful send count
    """
    total_sent = 0
    topic_stats = {}

    for i, (job, db_id) in enumerate(jobs):
        sent = await send_job_to_topics(bot, job, db_id)

        # Update DB with message IDs
        if sent:
            db.mark_job_sent(db_id, sent)

        for t_key in sent:
            topic_stats[t_key] = topic_stats.get(t_key, 0) + 1
            total_sent += 1

        if i < len(jobs) - 1:
            await _async_sleep(TELEGRAM_SEND_DELAY)

    if topic_stats:
        log.info("📊 Topic send summary:")
        for t_key, count in sorted(topic_stats.items()):
            t_name = CHANNELS.get(t_key, {}).get("name", t_key)
            log.info(f"  {t_name}: {count} jobs")

    return total_sent


async def _async_sleep(seconds: float) -> None:
    """Async sleep wrapper."""
    import asyncio
    await asyncio.sleep(seconds)
```

- [ ] **Step 2: Commit**

```bash
git add bot/sender.py
git commit -m "feat: add job sender with inline buttons and async Telegram API"
```

---

### Task 4: Callback Handlers (Inline Buttons)

**Files:**
- Create: `bot/callbacks.py`

- [ ] **Step 1: Write bot/callbacks.py**

```python
# bot/callbacks.py
"""
Inline button callback handlers.
Routes: save, share, similar, not_relevant, subscription steps, pagination.
"""

import logging
from telegram import Update, Bot
from telegram.ext import ContextTypes

from core import db
from core.models import Job
from bot.sender import format_job_message
from bot.keyboards import job_buttons

log = logging.getLogger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries to the appropriate handler."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()  # Acknowledge the button press

    data = query.data
    user = query.from_user

    if data.startswith("save:"):
        await _handle_save(query, user, data)
    elif data.startswith("share:"):
        await _handle_share(query, user, data)
    elif data.startswith("similar:"):
        await _handle_similar(query, user, context.bot, data)
    elif data.startswith("not_relevant:"):
        await _handle_not_relevant(query, user, data)
    elif data.startswith("sub_topic:"):
        await _handle_sub_topic(query, user, context, data)
    elif data == "sub_done":
        await _handle_sub_done(query, user, context)
    elif data.startswith("sub_seniority:"):
        await _handle_sub_seniority(query, user, context, data)
    elif data == "sub_seniority_done":
        await _handle_sub_seniority_done(query, user, context)
    elif data.startswith("saved_page:"):
        await _handle_saved_page(query, user, data)
    else:
        log.warning(f"Unknown callback data: {data}")


async def _handle_save(query, user, data: str) -> None:
    """Save a job for the user."""
    job_id = int(data.split(":")[1])
    db_user = db.get_or_create_user(user.id, user.username or "")
    saved = db.save_job_for_user(db_user["id"], job_id)

    if saved:
        try:
            await query.from_user.send_message("💾 Job saved! Use /saved to view your saved jobs.")
        except Exception:
            pass  # User may not have started a DM with the bot
        await query.answer("💾 Saved!", show_alert=False)
    else:
        await query.answer("Already saved", show_alert=False)


async def _handle_share(query, user, data: str) -> None:
    """Generate a shareable text for the job."""
    job_id = int(data.split(":")[1])
    row = db._fetchone("SELECT title, company, url FROM jobs WHERE id = %s", (job_id,))
    if not row:
        await query.answer("Job not found", show_alert=True)
        return

    share_text = f"🔗 {row['title']} at {row['company']}\n{row['url']}"
    try:
        await query.from_user.send_message(
            f"📤 Share this job:\n\n{share_text}\n\n(Copy and forward this message)",
        )
        await query.answer("📤 Check your DMs!", show_alert=False)
    except Exception:
        await query.answer("Start a DM with the bot first", show_alert=True)


async def _handle_similar(query, user, bot: Bot, data: str) -> None:
    """Find and send similar jobs via DM."""
    job_id = int(data.split(":")[1])
    row = db._fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
    if not row:
        await query.answer("Job not found", show_alert=True)
        return

    job = Job.from_db_row(row)

    # Find similar jobs using the ranking query from the spec
    try:
        similar = db._fetchall(
            """SELECT j.* FROM jobs j
               WHERE j.id != %s
                 AND j.created_at > now() - make_interval(days := 14)
               ORDER BY similarity(j.title, %s) DESC
               LIMIT 5""",
            (job_id, job.title),
        )
    except Exception as e:
        log.error(f"Similar jobs query failed: {e}")
        similar = []

    if not similar:
        await query.answer("No similar jobs found", show_alert=True)
        return

    try:
        await query.from_user.send_message("🔍 Similar jobs:")
        for s_row in similar:
            s_job = Job.from_db_row(s_row)
            msg = format_job_message(s_job)
            await query.from_user.send_message(
                msg, parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=job_buttons(s_row["id"]),
            )
        await query.answer("🔍 Check your DMs!", show_alert=False)
    except Exception:
        await query.answer("Start a DM with the bot first", show_alert=True)


async def _handle_not_relevant(query, user, data: str) -> None:
    """Record negative feedback."""
    job_id = int(data.split(":")[1])
    db_user = db.get_or_create_user(user.id, user.username or "")
    db.add_feedback(job_id, db_user["id"], "not_relevant")
    await query.answer("Thanks for the feedback!", show_alert=False)


async def _handle_sub_topic(query, user, context, data: str) -> None:
    """Toggle a topic in the subscription builder."""
    topic = data.split(":")[1]
    # Store temporary selection in context.user_data
    selected = context.user_data.get("sub_topics", set())
    if topic in selected:
        selected.discard(topic)
    else:
        selected.add(topic)
    context.user_data["sub_topics"] = selected

    from bot.keyboards import topic_selection_keyboard
    await query.edit_message_reply_markup(
        reply_markup=topic_selection_keyboard(selected)
    )


async def _handle_sub_done(query, user, context) -> None:
    """Topic selection done, move to seniority."""
    topics = context.user_data.get("sub_topics", set())
    if not topics:
        await query.answer("Select at least one topic", show_alert=True)
        return
    context.user_data["sub_seniority"] = set()
    from bot.keyboards import seniority_selection_keyboard
    await query.edit_message_text(
        "Step 2/3: Select seniority levels (or skip):",
        reply_markup=seniority_selection_keyboard(),
    )


async def _handle_sub_seniority(query, user, context, data: str) -> None:
    """Toggle a seniority level in the subscription builder."""
    level = data.split(":")[1]
    selected = context.user_data.get("sub_seniority", set())
    if level in selected:
        selected.discard(level)
    else:
        selected.add(level)
    context.user_data["sub_seniority"] = selected

    from bot.keyboards import seniority_selection_keyboard
    await query.edit_message_reply_markup(
        reply_markup=seniority_selection_keyboard(selected)
    )


async def _handle_sub_seniority_done(query, user, context) -> None:
    """Seniority selection done, save subscription."""
    topics = list(context.user_data.get("sub_topics", set()))
    seniority = list(context.user_data.get("sub_seniority", set()))

    subscriptions = {"topics": topics}
    if seniority:
        subscriptions["seniority"] = seniority

    db_user = db.get_or_create_user(user.id, user.username or "")
    db.update_user_subscriptions(user.id, subscriptions)

    summary = f"Topics: {', '.join(topics)}"
    if seniority:
        summary += f"\nSeniority: {', '.join(seniority)}"

    await query.edit_message_text(f"✅ Subscribed!\n\n{summary}\n\nYou'll receive DM alerts for matching jobs.")

    # Clean up temp data
    context.user_data.pop("sub_topics", None)
    context.user_data.pop("sub_seniority", None)


async def _handle_saved_page(query, user, data: str) -> None:
    """Handle saved jobs pagination."""
    page = int(data.split(":")[1])
    # Delegate to the saved command with page param
    from bot.commands import _show_saved_page
    await _show_saved_page(query, user, page)
```

- [ ] **Step 2: Commit**

```bash
git add bot/callbacks.py
git commit -m "feat: add callback handlers for inline buttons and subscription flow"
```

---

### Task 5: Bot Commands

**Files:**
- Create: `bot/commands.py`

- [ ] **Step 1: Write bot/commands.py**

```python
# bot/commands.py
"""
Bot command handlers.
All commands use interactive inline keyboards instead of free-text parsing.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core import db
from core.models import Job
from bot.sender import format_job_message
from bot.keyboards import (
    topic_selection_keyboard, job_buttons, pagination_keyboard,
)

log = logging.getLogger(__name__)

HELP_TEXT = """
🤖 <b>Programming Jobs Bot</b>

<b>Commands:</b>
/subscribe — Set up personalized job alerts
/unsubscribe — Remove all subscriptions
/mysubs — View your current filters
/search — Search jobs interactively
/saved — View your saved jobs
/stats — Bot statistics
/top — Top jobs this week
/salary — Salary insights
/help — This message
"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome! I post programming jobs from 15 sources.\n\n"
        "Use /subscribe to get personalized alerts, or /help for all commands.",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the interactive subscription flow."""
    context.user_data["sub_topics"] = set()
    await update.message.reply_text(
        "Step 1/3: Select topics you're interested in:",
        reply_markup=topic_selection_keyboard(),
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    db.update_user_subscriptions(user.id, {})
    await update.message.reply_text("✅ All subscriptions removed.")


async def cmd_mysubs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    subs = db_user.get("subscriptions", {})

    if not subs or not subs.get("topics"):
        await update.message.reply_text("No active subscriptions. Use /subscribe to set up alerts.")
        return

    lines = ["📋 <b>Your Subscriptions:</b>\n"]
    if subs.get("topics"):
        lines.append(f"Topics: {', '.join(subs['topics'])}")
    if subs.get("seniority"):
        lines.append(f"Seniority: {', '.join(subs['seniority'])}")
    if subs.get("keywords"):
        lines.append(f"Keywords: {', '.join(subs['keywords'])}")
    if subs.get("min_salary"):
        lines.append(f"Min salary: ${subs['min_salary']:,}/year")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search jobs. Usage: /search <query>"""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /search <keywords>\n"
            "Example: /search python remote\n"
            "Example: /search react senior"
        )
        return

    query = " ".join(args)
    try:
        results = db._fetchall(
            """SELECT * FROM jobs
               WHERE created_at > now() - make_interval(days := 14)
                 AND (title ILIKE %s OR %s = ANY(tags))
               ORDER BY created_at DESC
               LIMIT 5""",
            (f"%{query}%", query.lower()),
        )
    except Exception as e:
        log.error(f"Search failed: {e}")
        results = []

    if not results:
        await update.message.reply_text(f"No jobs found for '{query}'. Try broader keywords.")
        return

    await update.message.reply_text(f"🔍 Found {len(results)} jobs for '{query}':")
    for row in results:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        await update.message.reply_text(
            msg, parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=job_buttons(row["id"]),
        )


async def cmd_saved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show saved jobs."""
    user = update.effective_user
    await _show_saved_page(update, user, page=1)


async def _show_saved_page(update_or_query, user, page: int) -> None:
    """Show a page of saved jobs. Works with both Update and CallbackQuery."""
    per_page = 5
    offset = (page - 1) * per_page

    db_user = db.get_or_create_user(user.id, user.username or "")
    saved = db.get_saved_jobs(db_user["id"], limit=per_page + 1, offset=offset)

    has_more = len(saved) > per_page
    saved = saved[:per_page]

    if not saved:
        text = "No saved jobs yet. Tap 💾 Save on any job post!"
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(text)
        else:
            await update_or_query.edit_message_text(text)
        return

    total_pages = page + (1 if has_more else 0)  # Approximate
    header = f"💾 <b>Saved Jobs</b> (page {page}):\n"

    if hasattr(update_or_query, "message") and update_or_query.message:
        send_fn = update_or_query.message.reply_text
    else:
        send_fn = update_or_query.edit_message_text

    await send_fn(header, parse_mode="HTML")
    for row in saved:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(
                msg, parse_mode="HTML",
                disable_web_page_preview=True,
            )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics."""
    try:
        today = db._fetchone(
            "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 1)"
        )
        week = db._fetchone(
            "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 7)"
        )
        total = db._fetchone("SELECT COUNT(*) as count FROM jobs")
        sources = db._fetchall(
            """SELECT source, COUNT(*) as count FROM jobs
               WHERE created_at > now() - make_interval(days := 7)
               GROUP BY source ORDER BY count DESC LIMIT 5"""
        )
    except Exception as e:
        await update.message.reply_text(f"Stats unavailable: {e}")
        return

    lines = [
        "📊 <b>Bot Statistics</b>\n",
        f"Today: {today['count']} jobs",
        f"This week: {week['count']} jobs",
        f"All time: {total['count']} jobs",
        "\n<b>Top sources (7 days):</b>",
    ]
    for s in sources:
        lines.append(f"  {s['source']}: {s['count']}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show top jobs this week by engagement."""
    try:
        top_jobs = db._fetchall(
            """SELECT j.*, COUNT(jf.id) as engagement
               FROM jobs j
               LEFT JOIN job_feedback jf ON j.id = jf.job_id
               LEFT JOIN user_saved_jobs usj ON j.id = usj.job_id
               WHERE j.created_at > now() - make_interval(days := 7)
               GROUP BY j.id
               ORDER BY engagement DESC, j.created_at DESC
               LIMIT 5"""
        )
    except Exception as e:
        await update.message.reply_text(f"Top jobs unavailable: {e}")
        return

    if not top_jobs:
        await update.message.reply_text("No jobs this week yet.")
        return

    await update.message.reply_text("🏆 <b>Top Jobs This Week:</b>", parse_mode="HTML")
    for row in top_jobs:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        await update.message.reply_text(
            msg, parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=job_buttons(row["id"]),
        )


async def cmd_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show salary insights. Usage: /salary <role>"""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /salary <role>\n"
            "Example: /salary python\n"
            "Example: /salary backend"
        )
        return

    query = " ".join(args)
    try:
        stats = db._fetchone(
            """SELECT
                 COUNT(*) as count,
                 AVG(salary_min) as avg_min,
                 AVG(salary_max) as avg_max,
                 MIN(salary_min) as lowest,
                 MAX(salary_max) as highest
               FROM jobs
               WHERE salary_min IS NOT NULL
                 AND title ILIKE %s
                 AND created_at > now() - make_interval(days := 30)""",
            (f"%{query}%",),
        )
    except Exception as e:
        await update.message.reply_text(f"Salary data unavailable: {e}")
        return

    if not stats or not stats["count"] or stats["count"] == 0:
        await update.message.reply_text(f"No salary data for '{query}'.")
        return

    lines = [
        f"💰 <b>Salary Insights: {query}</b>\n",
        f"Based on {stats['count']} jobs (last 30 days)\n",
        f"Average: ${int(stats['avg_min']):,} - ${int(stats['avg_max']):,}/year",
        f"Range: ${int(stats['lowest']):,} - ${int(stats['highest']):,}/year",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
```

- [ ] **Step 2: Commit**

```bash
git add bot/commands.py
git commit -m "feat: add bot commands (subscribe, search, saved, stats, top, salary)"
```

---

### Task 6: DM Notifications

**Files:**
- Create: `bot/notifications.py`

- [ ] **Step 1: Write bot/notifications.py**

```python
# bot/notifications.py
"""
Personalized DM alerts for subscribed users.
Called after new jobs are sent to the group, sends matching jobs to subscribers via DM.
"""

import logging
from telegram import Bot
from telegram.error import TelegramError

from core import db
from core.models import Job
from bot.sender import format_job_message
from bot.keyboards import job_buttons

log = logging.getLogger(__name__)

# Rate limit: max DMs per user per hour
MAX_DMS_PER_USER_PER_HOUR = 20


def _job_matches_subscription(job: Job, subs: dict) -> bool:
    """Check if a job matches a user's subscription filters."""
    if not subs:
        return False

    # Check topics
    sub_topics = set(subs.get("topics", []))
    if sub_topics and not sub_topics.intersection(set(job.topics)):
        return False

    # Check seniority
    sub_seniority = subs.get("seniority", [])
    if sub_seniority and job.seniority not in sub_seniority:
        return False

    # Check keywords
    sub_keywords = subs.get("keywords", [])
    if sub_keywords:
        title_lower = job.title.lower()
        if not any(kw.lower() in title_lower for kw in sub_keywords):
            return False

    # Check min salary
    min_salary = subs.get("min_salary")
    if min_salary and job.salary_max and job.salary_max < min_salary:
        return False

    return True


async def notify_subscribers(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send DM alerts to subscribed users for matching jobs.

    Args:
        bot: Telegram Bot instance
        jobs: List of (Job, db_id) tuples

    Returns: Total DMs sent
    """
    # Get all users with subscriptions and notify_dm=True
    try:
        users = db._fetchall(
            "SELECT * FROM users WHERE notify_dm = TRUE AND subscriptions != '{}'"
        )
    except Exception as e:
        log.error(f"Failed to fetch subscribers: {e}")
        return 0

    total_sent = 0

    for user_row in users:
        subs = user_row.get("subscriptions", {})
        telegram_id = user_row["telegram_id"]
        dm_count = 0

        for job, db_id in jobs:
            if dm_count >= MAX_DMS_PER_USER_PER_HOUR:
                log.info(f"Rate limit hit for user {telegram_id}")
                break

            if not _job_matches_subscription(job, subs):
                continue

            try:
                msg = format_job_message(job)
                await bot.send_message(
                    chat_id=telegram_id,
                    text=f"🔔 New matching job:\n\n{msg}",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=job_buttons(db_id),
                )
                dm_count += 1
                total_sent += 1
            except TelegramError as e:
                if "bot was blocked" in str(e).lower() or "user not found" in str(e).lower():
                    # User blocked the bot or deleted account — disable notifications
                    db._execute(
                        "UPDATE users SET notify_dm = FALSE WHERE telegram_id = %s",
                        (telegram_id,),
                    )
                    log.info(f"Disabled DMs for user {telegram_id}: {e}")
                    break
                else:
                    log.warning(f"DM failed for {telegram_id}: {e}")

    log.info(f"📬 Sent {total_sent} DM alerts to {len(users)} subscribers")
    return total_sent
```

- [ ] **Step 2: Commit**

```bash
git add bot/notifications.py
git commit -m "feat: add DM notification system for subscribed users"
```

---

### Task 7: Final Verification

- [ ] **Step 1: Verify all imports**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from bot.app import get_app, start_polling, stop_polling
from bot.sender import format_job_message, send_job_to_topics
from bot.callbacks import handle_callback
from bot.commands import cmd_help, cmd_subscribe, cmd_search
from bot.notifications import notify_subscribers
from bot.keyboards import job_buttons, topic_selection_keyboard
print('All bot modules imported OK')
"
```
Expected: "All bot modules imported OK"

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "feat: complete Plan 3 — interactive Telegram bot"
```

---

## Summary

After completing this plan, the project has:

- **Polling-based bot** — no webhook cold-start issues on free tier
- **Inline buttons** on every job (Save, Share, Similar, Not Relevant)
- **10 commands** — /subscribe (interactive), /search, /saved, /stats, /top, /salary, etc.
- **DM subscription alerts** — with rate limiting and auto-disable on block
- **Interactive subscription flow** — multi-step inline keyboard (topics → seniority → done)

**Next:** Plan 4 (Operational Reliability) adds circuit breaker, run tracking, monitoring, and alerts.
