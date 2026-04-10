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
        ("fullstack", "🔄 Full Stack"),
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
