"""
Inline button callback handlers.
Routes: save, share, similar, not_relevant, subscription steps, pagination.
"""

import logging
from telegram import Update, Bot
from telegram.ext import ContextTypes

from core import db
from core.config import ADMIN_TELEGRAM_ID
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
    elif data.startswith("applied:"):
        await _handle_applied(query, user, data)
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
    elif data.startswith("sub_location:"):
        await _handle_sub_location(query, user, context, data)
    elif data == "sub_location_done":
        await _handle_sub_location_done(query, user, context)
    elif data.startswith("sub_source:"):
        await _handle_sub_source(query, user, context, data)
    elif data == "sub_source_done":
        await _handle_sub_source_done(query, user, context)
    elif data.startswith("saved_page:"):
        await _handle_saved_page(query, user, data)
    elif data.startswith("msg_read:"):
        await _handle_msg_read(query, user, data)
    elif data.startswith("unsub:"):
        await _handle_unsub(query, user, context, data)
    elif data.startswith("del:"):
        await _handle_del(query, user, context, data)
    elif data.startswith("dm:"):
        await _handle_dm(query, user, context, data)
    elif data.startswith("edit:"):
        await _handle_edit(query, user, context, data)
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


async def _handle_applied(query, user, data: str) -> None:
    """Record that the user applied to this job."""
    job_id = int(data.split(":")[1])
    db_user = db.get_or_create_user(user.id, user.username or "")
    is_new = db.mark_applied(db_user["id"], job_id)

    if is_new:
        streak = db.get_streak(db_user["id"])
        total = db.get_application_count(db_user["id"])
        streak_msg = f"🔥 Streak: {streak['current']} day{'s' if streak['current'] != 1 else ''}"
        try:
            await query.from_user.send_message(
                f"✅ Marked as applied! (#{total} total)\n{streak_msg}\n\n"
                f"Use /applied to see your history, /streak for details."
            )
        except Exception:
            pass
        await query.answer("✅ Applied!", show_alert=False)
    else:
        await query.answer("Already marked as applied", show_alert=False)


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
        "Step 2/4: Select seniority levels (or skip for all):",
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
    """Seniority selection done, move to location."""
    context.user_data["sub_locations"] = set()
    from bot.keyboards import location_selection_keyboard
    await query.edit_message_text(
        "Step 3/4: Select preferred locations (or skip for all):",
        reply_markup=location_selection_keyboard(),
    )


async def _handle_sub_location(query, user, context, data: str) -> None:
    """Toggle a location in the subscription builder."""
    location = data.split(":")[1]
    selected = context.user_data.get("sub_locations", set())
    if location in selected:
        selected.discard(location)
    else:
        selected.add(location)
    context.user_data["sub_locations"] = selected

    from bot.keyboards import location_selection_keyboard
    await query.edit_message_reply_markup(
        reply_markup=location_selection_keyboard(selected)
    )


async def _handle_sub_location_done(query, user, context) -> None:
    """Location selection done, move to source selection."""
    context.user_data["sub_sources"] = set()
    from bot.keyboards import source_selection_keyboard
    await query.edit_message_text(
        "Step 4/4: Select job sources (or skip for all):",
        reply_markup=source_selection_keyboard(),
    )


async def _handle_sub_source(query, user, context, data: str) -> None:
    """Toggle a source in the subscription builder."""
    source = data.split(":")[1]
    selected = context.user_data.get("sub_sources", set())
    if source in selected:
        selected.discard(source)
    else:
        selected.add(source)
    context.user_data["sub_sources"] = selected

    from bot.keyboards import source_selection_keyboard
    await query.edit_message_reply_markup(
        reply_markup=source_selection_keyboard(selected)
    )


async def _handle_sub_source_done(query, user, context) -> None:
    """Source selection done — save the alert (create or edit)."""
    topics = list(context.user_data.get("sub_topics", set()))
    seniority = list(context.user_data.get("sub_seniority", set()))
    locations = list(context.user_data.get("sub_locations", set()))
    sources = list(context.user_data.get("sub_sources", set()))

    alert_payload = {
        "topics": topics,
        "seniority": seniority,
        "locations": locations,
        "sources": sources,
        "keywords": list(context.user_data.get("sub_keywords", [])),
        "min_salary": context.user_data.get("sub_min_salary"),
    }

    db_user = db.get_or_create_user(user.id, user.username or "")
    edit_position = context.user_data.pop("edit_position", None)

    if edit_position is not None:
        ok = db.update_user_alert(db_user["id"], edit_position, alert_payload)
        if ok:
            header = f"✅ Alert #{edit_position} updated."
        else:
            header = f"⚠️ Alert #{edit_position} no longer exists."
    else:
        new_id = db.create_user_alert(db_user["id"], alert_payload)
        # Look up its position to show in the confirmation
        alerts = db.get_user_alerts(db_user["id"])
        position = next((a["position"] for a in alerts if a["id"] == new_id), len(alerts))
        header = f"✅ Alert #{position} created. You'll receive DM alerts for matching jobs."

    summary = _format_sub_summary(topics, seniority, locations, sources)
    await query.edit_message_text(f"{header}\n\n{summary}")

    # Clean up temp data
    context.user_data.pop("sub_topics", None)
    context.user_data.pop("sub_seniority", None)
    context.user_data.pop("sub_locations", None)
    context.user_data.pop("sub_sources", None)
    context.user_data.pop("sub_keywords", None)
    context.user_data.pop("sub_min_salary", None)


def _format_sub_summary(topics, seniority, locations, sources) -> str:
    """Build human-readable subscription summary."""
    summary = f"Topics: {', '.join(topics)}"
    if seniority:
        summary += f"\nSeniority: {', '.join(seniority)}"
    if locations:
        from bot.keyboards import LOCATION_OPTIONS
        label_map = dict(LOCATION_OPTIONS)
        summary += f"\nLocations: {', '.join(label_map.get(l, l) for l in locations)}"
    else:
        summary += "\nLocations: All (no filter)"
    if sources:
        from bot.keyboards import SOURCE_OPTIONS
        label_map = dict(SOURCE_OPTIONS)
        summary += f"\nSources: {', '.join(label_map.get(s, s) for s in sources)}"
    else:
        summary += "\nSources: All (no filter)"
    return summary


async def _handle_saved_page(query, user, data: str) -> None:
    """Handle saved jobs pagination."""
    page = int(data.split(":")[1])
    # Delegate to the saved command with page param
    from bot.commands import _show_saved_page
    await _show_saved_page(query, user, page)


async def _handle_msg_read(query, user, data: str) -> None:
    """Mark a support message as read (admin only)."""
    if not ADMIN_TELEGRAM_ID or str(user.id) != ADMIN_TELEGRAM_ID:
        await query.answer("Admin only", show_alert=True)
        return

    message_id = int(data.split(":")[1])
    db.mark_support_message_read(message_id)

    await query.edit_message_text(
        query.message.text_html + "\n\n<i>✅ Marked as read</i>",
        parse_mode="HTML",
    )
    await query.answer("Marked as read")


async def _handle_unsub(query, user, context, data: str) -> None:
    """Handle /unsubscribe chooser callbacks: unsub:<n>, unsub:all, unsub:all_confirm, unsub:cancel."""
    action = data.split(":", 1)[1]
    db_user = db.get_or_create_user(user.id, user.username or "")

    if action == "cancel":
        await query.edit_message_text("Cancelled.")
        return

    if action == "all":
        from bot.keyboards import confirm_remove_all_keyboard
        alerts = db.get_user_alerts(db_user["id"])
        await query.edit_message_text(
            f"⚠️ Remove ALL {len(alerts)} alerts? This cannot be undone.",
            reply_markup=confirm_remove_all_keyboard(),
        )
        return

    if action == "all_confirm":
        count = db.delete_all_user_alerts(db_user["id"])
        await query.edit_message_text(f"✅ Removed {count} alert(s).")
        return

    # unsub:<n>
    try:
        position = int(action)
    except ValueError:
        log.warning(f"Bad unsub callback: {data}")
        return

    ok = db.delete_user_alert(db_user["id"], position)
    if not ok:
        await query.edit_message_text(f"⚠️ Alert #{position} no longer exists.")
        return
    remaining = len(db.get_user_alerts(db_user["id"]))
    await query.edit_message_text(
        f"✅ Alert #{position} removed. You have {remaining} alert(s) left."
    )
