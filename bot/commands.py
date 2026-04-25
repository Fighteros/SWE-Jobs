"""
Bot command handlers.
All commands use interactive inline keyboards instead of free-text parsing.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core import db
from core.config import ADMIN_TELEGRAM_ID, TELEGRAM_GROUP_ID
from core.models import Job
from core.channels import get_topic_thread_id
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
/applied — View your application history
/streak — Your daily application streak
/blacklist — Manage blocked companies/keywords
/contact — Send a message to the bot owner
/stats — Bot statistics
/top — Top jobs this week
/salary — Salary insights
/help — This message
"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ensure user exists in DB so DM alerts can reach them
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "")

    # Handle deep link from group (/start subscribe)
    if context.args and context.args[0] == "subscribe":
        await update.message.reply_text(
            "👋 Great, now I can send you DM alerts!\n\n"
            "Let's set up your subscription:",
            parse_mode="HTML",
        )
        context.user_data["sub_topics"] = set()
        await update.message.reply_text(
            "Step 1/4: Select topics you're interested in:\n"
            "(tap to toggle, then press Done)",
            reply_markup=topic_selection_keyboard(),
        )
        return

    await update.message.reply_text(
        "👋 Welcome! I post programming jobs from 23 sources.\n\n"
        "Use /subscribe to get personalized alerts, or /help for all commands.",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the interactive subscription flow."""
    # If subscribing from a group, remind user to start a private chat first
    if update.effective_chat.type != "private":
        bot_user = await context.bot.get_me()
        await update.message.reply_text(
            "⚠️ To receive DM alerts, you must first start a private chat with me.\n\n"
            f"👉 <a href=\"https://t.me/{bot_user.username}?start=subscribe\">Click here to open a DM</a> "
            "and send /subscribe there.",
            parse_mode="HTML",
        )
        return

    context.user_data["sub_topics"] = set()
    await update.message.reply_text(
        "Step 1/4: Select topics you're interested in:\n"
        "(tap to toggle, then press Done)",
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
    if subs.get("locations"):
        from bot.keyboards import LOCATION_OPTIONS
        label_map = dict(LOCATION_OPTIONS)
        lines.append(f"Locations: {', '.join(label_map.get(l, l) for l in subs['locations'])}")
    if subs.get("sources"):
        from bot.keyboards import SOURCE_OPTIONS
        label_map = dict(SOURCE_OPTIONS)
        lines.append(f"Sources: {', '.join(label_map.get(s, s) for s in subs['sources'])}")
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

    # Determine how to send messages
    if hasattr(update_or_query, "message") and update_or_query.message:
        reply_fn = update_or_query.message.reply_text
    else:
        reply_fn = update_or_query.message.reply_text  # CallbackQuery.message

    if not saved:
        text = "No saved jobs yet. Tap 💾 Save on any job post!"
        await reply_fn(text)
        return

    total_pages = page + (1 if has_more else 0)
    header = f"💾 <b>Saved Jobs</b> (page {page}):\n"
    await reply_fn(header, parse_mode="HTML")

    for row in saved:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        await reply_fn(
            msg, parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=job_buttons(row["id"]),
        )

    # Pagination buttons
    nav = pagination_keyboard(page, total_pages, "saved_page")
    if nav:
        await reply_fn("Page navigation:", reply_markup=nav)


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
    """Egyptian salary insights via egytech.fyi. Usage: /salary <role> [seniority] [yoe]"""
    from core.egytech import get_stats
    from core.egytech_mapping import parse_role_query, SENIORITY_TO_LEVEL

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /salary <role> [seniority] [yoe]\n"
            "Examples:\n"
            "  /salary backend\n"
            "  /salary frontend mid\n"
            "  /salary devops senior 5\n\n"
            "Roles: backend, frontend, fullstack, mobile, devops, qa, security, "
            "data engineer, data scientist, embedded, ui ux, product manager"
        )
        return

    # Parse positional args: role (1+ words), seniority (single word from our enum), yoe (int).
    raw = list(args)
    yoe: int | None = None
    if raw and raw[-1].isdigit():
        yoe = int(raw.pop())

    seniority: str | None = None
    if raw and raw[-1].lower() in SENIORITY_TO_LEVEL:
        seniority = raw.pop().lower()

    role_text = " ".join(raw).strip().lower()
    title = parse_role_query(role_text)

    if not title:
        await update.message.reply_text(
            f"No data for '{role_text}'.\n\n"
            "Try one of: backend, frontend, fullstack, mobile, devops, qa, security, "
            "data engineer, data scientist, embedded, ui ux, product manager."
        )
        return

    level = SENIORITY_TO_LEVEL.get(seniority) if seniority else None
    yoe_from = yoe
    yoe_to = yoe + 1 if yoe is not None else None

    data = get_stats(title=title, level=level, yoe_from=yoe_from, yoe_to=yoe_to)
    if not data or "stats" not in data:
        await update.message.reply_text(
            f"No data for {title} / {seniority or 'any'} / yoe={yoe if yoe is not None else 'any'}.\n"
            "Try a broader filter."
        )
        return

    s = data["stats"]
    header = f"💰 {title}"
    if seniority:
        header += f" / {seniority}"
    if yoe is not None:
        header += f" / {yoe} yoe"
    header += f" · n={s.get('totalCount', 0)}"

    lines = [
        header,
        f"Median: EGP {s.get('median', 0):,}/mo",
        f"P20–P75: EGP {s.get('p20Compensation', 0):,} – {s.get('p75Compensation', 0):,}/mo",
        f"P90: EGP {s.get('p90Compensation', 0):,}/mo",
        "Source: egytech.fyi April 2024",
    ]
    await update.message.reply_text("\n".join(lines))


# ── Application tracking ────────────────────────────────────


async def cmd_applied(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's application history."""
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")

    total = db.get_application_count(db_user["id"])
    if total == 0:
        await update.message.reply_text(
            "No applications tracked yet.\n"
            "Tap ✅ Applied on any job post to start tracking!"
        )
        return

    rows = db.get_application_history(db_user["id"], limit=10)

    lines = [f"📋 <b>Application History</b> ({total} total)\n"]
    for row in rows:
        title = _escape_html(row["title"])
        company = _escape_html(row.get("company", ""))
        applied_at = row["applied_at"].strftime("%b %d")
        lines.append(f"• <b>{title}</b> at {company} — {applied_at}")

    streak = db.get_streak(db_user["id"])
    lines.append(f"\n🔥 Current streak: {streak['current']} day{'s' if streak['current'] != 1 else ''}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_streak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's application streak."""
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")

    streak = db.get_streak(db_user["id"])
    total = db.get_application_count(db_user["id"])

    if total == 0:
        await update.message.reply_text(
            "No applications tracked yet.\n"
            "Tap ✅ Applied on any job post to start your streak!"
        )
        return

    today_check = "✅ Applied today!" if streak["today"] else "⬜ Not yet applied today"

    lines = [
        "🔥 <b>Application Streak</b>\n",
        f"Current streak: <b>{streak['current']}</b> day{'s' if streak['current'] != 1 else ''}",
        f"Longest streak: <b>{streak['longest']}</b> day{'s' if streak['longest'] != 1 else ''}",
        f"Total applications: <b>{total}</b>",
        f"\n{today_check}",
    ]

    # Motivational nudge
    if streak["current"] >= 7:
        lines.append("\n🏆 Amazing consistency! Keep it up!")
    elif streak["current"] >= 3:
        lines.append("\n💪 Great momentum! Don't break the chain!")
    elif not streak["today"]:
        lines.append("\n👉 Apply to a job today to keep your streak alive!")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Blacklist ───────────────────────────────────────────────


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage blacklisted companies and keywords.

    Usage:
        /blacklist                      — view current blacklist
        /blacklist add company Acme     — block a company
        /blacklist add keyword recruiter — block a keyword
        /blacklist remove company Acme  — unblock a company
        /blacklist remove keyword recruiter — unblock a keyword
        /blacklist clear                — clear entire blacklist
    """
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    args = context.args or []

    bl = db.get_blacklist(db_user["id"])

    # No args — show current blacklist
    if not args:
        if not bl["companies"] and not bl["keywords"]:
            await update.message.reply_text(
                "Your blacklist is empty.\n\n"
                "<b>Usage:</b>\n"
                "/blacklist add company Acme Corp\n"
                "/blacklist add keyword recruiter\n"
                "/blacklist remove company Acme Corp\n"
                "/blacklist clear",
                parse_mode="HTML",
            )
            return

        lines = ["🚫 <b>Your Blacklist</b>\n"]
        if bl["companies"]:
            lines.append("<b>Companies:</b>")
            for c in bl["companies"]:
                lines.append(f"  • {_escape_html(c)}")
        if bl["keywords"]:
            lines.append("<b>Keywords:</b>")
            for k in bl["keywords"]:
                lines.append(f"  • {_escape_html(k)}")
        lines.append("\nJobs matching these are excluded from your DM alerts.")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    action = args[0].lower()

    if action == "clear":
        db.update_blacklist(db_user["id"], {"companies": [], "keywords": []})
        await update.message.reply_text("✅ Blacklist cleared.")
        return

    if action not in ("add", "remove") or len(args) < 3:
        await update.message.reply_text(
            "Usage: /blacklist add|remove company|keyword <value>\n"
            "Example: /blacklist add company Acme Corp"
        )
        return

    category = args[1].lower()
    value = " ".join(args[2:])

    if category not in ("company", "keyword"):
        await update.message.reply_text("Category must be 'company' or 'keyword'.")
        return

    list_key = "companies" if category == "company" else "keywords"

    if action == "add":
        if value.lower() not in [v.lower() for v in bl[list_key]]:
            bl[list_key].append(value)
            db.update_blacklist(db_user["id"], bl)
            await update.message.reply_text(f"✅ Added {category} '{_escape_html(value)}' to blacklist.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"Already blacklisted.")

    elif action == "remove":
        lower_values = [v.lower() for v in bl[list_key]]
        if value.lower() in lower_values:
            idx = lower_values.index(value.lower())
            bl[list_key].pop(idx)
            db.update_blacklist(db_user["id"], bl)
            await update.message.reply_text(f"✅ Removed {category} '{_escape_html(value)}' from blacklist.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"'{_escape_html(value)}' not found in blacklist.", parse_mode="HTML")


# ── Contact / Support ─────────────────────────────────────────

CONTACT_CATEGORIES = ("general", "bug", "feature")


async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a support message to the bot owner.

    Usage:
        /contact <message>
        /contact bug <message>
        /contact feature <message>
    """
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "<b>Contact the bot owner</b>\n\n"
            "<b>Usage:</b>\n"
            "/contact Your message here\n"
            "/contact bug Something is broken\n"
            "/contact feature I'd like to see ...\n\n"
            "Categories: general (default), bug, feature",
            parse_mode="HTML",
        )
        return

    # Check if first word is a category
    category = "general"
    message_parts = args
    if args[0].lower() in CONTACT_CATEGORIES:
        category = args[0].lower()
        message_parts = args[1:]

    if not message_parts:
        await update.message.reply_text("Please include a message after the category.")
        return

    message_text = " ".join(message_parts)

    if len(message_text) > 2000:
        await update.message.reply_text("Message too long. Please keep it under 2000 characters.")
        return

    db.create_support_message(
        user_id=db_user["id"],
        telegram_id=user.id,
        username=user.username or "",
        message=message_text,
        category=category,
    )

    await update.message.reply_text(
        f"✅ Message sent! Category: <b>{category}</b>\n\n"
        "The bot owner will review it. Thanks for your feedback!",
        parse_mode="HTML",
    )

    # Notify admin in real-time if configured
    if ADMIN_TELEGRAM_ID:
        try:
            admin_id = int(ADMIN_TELEGRAM_ID)
            sender = f"@{user.username}" if user.username else f"User #{user.id}"
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"📩 <b>New support message</b>\n\n"
                    f"From: {_escape_html(sender)}\n"
                    f"Category: {category}\n"
                    f"Message: {_escape_html(message_text[:500])}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            log.warning(f"Failed to notify admin of support message: {e}")


async def cmd_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only: list unread support messages.

    Usage:
        /messages           — list unread messages
        /messages readall   — mark all as read
    """
    user = update.effective_user
    if not ADMIN_TELEGRAM_ID or str(user.id) != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("This command is only available to the bot admin.")
        return

    args = context.args or []

    if args and args[0].lower() == "readall":
        count = db.mark_all_support_messages_read()
        await update.message.reply_text(f"✅ Marked {count} message(s) as read.")
        return

    unread_count = db.count_unread_support_messages()
    if unread_count == 0:
        await update.message.reply_text("No unread messages.")
        return

    messages = db.get_unread_support_messages(limit=10)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    await update.message.reply_text(
        f"📬 <b>Unread Messages</b> ({unread_count} total)\n",
        parse_mode="HTML",
    )

    for msg in messages:
        sender = f"@{msg['username']}" if msg['username'] else f"User #{msg['telegram_id']}"
        created = msg["created_at"].strftime("%b %d, %H:%M")
        text = (
            f"<b>#{msg['id']}</b> [{msg['category']}] — {created}\n"
            f"From: {_escape_html(sender)}\n\n"
            f"{_escape_html(msg['message'][:500])}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Mark Read", callback_data=f"msg_read:{msg['id']}")]
        ])
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=keyboard,
        )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only: broadcast a message to #general topic.

    Usage:
        /broadcast <message>          — send plain text
        /broadcast html <message>     — send with HTML formatting
        /broadcast topic:<key> <msg>  — send to a specific topic (e.g. topic:backend)
    """
    user = update.effective_user
    if not ADMIN_TELEGRAM_ID or str(user.id) != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("This command is only available to the bot admin.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "/broadcast <message>\n"
            "/broadcast html <b>formatted</b> message\n"
            "/broadcast topic:backend Your message here"
        )
        return

    # Parse options
    topic_key = "general"
    use_html = False
    text_args = list(args)

    # Check for topic: prefix
    if text_args[0].startswith("topic:"):
        topic_key = text_args.pop(0).split(":", 1)[1]

    # Check for html flag
    if text_args and text_args[0].lower() == "html":
        use_html = True
        text_args.pop(0)

    message = " ".join(text_args)
    if not message:
        await update.message.reply_text("Message cannot be empty.")
        return

    thread_id = get_topic_thread_id(topic_key)
    if thread_id is None:
        await update.message.reply_text(f"Topic '{topic_key}' not configured (env var not set).")
        return

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_GROUP_ID,
            message_thread_id=thread_id,
            text=message,
            parse_mode="HTML" if use_html else None,
            disable_web_page_preview=True,
        )
        await update.message.reply_text(f"✅ Broadcast sent to #{topic_key}!")
    except Exception as e:
        log.error(f"Broadcast failed: {e}")
        await update.message.reply_text(f"❌ Failed to send: {e}")
