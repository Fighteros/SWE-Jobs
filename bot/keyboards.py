"""
Inline keyboard builders for job messages and interactive commands.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def job_buttons(job_id: int) -> InlineKeyboardMarkup:
    """Build the inline buttons shown under each job message."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Save", callback_data=f"save:{job_id}"),
            InlineKeyboardButton("✅ Applied", callback_data=f"applied:{job_id}"),
            InlineKeyboardButton("📤 Share", callback_data=f"share:{job_id}"),
        ],
        [
            InlineKeyboardButton("🔍 Similar", callback_data=f"similar:{job_id}"),
            InlineKeyboardButton("👎 Not Relevant", callback_data=f"not_relevant:{job_id}"),
        ],
    ])


def topic_selection_keyboard(selected: set[str] = None) -> InlineKeyboardMarkup:
    """Build topic selection keyboard for /subscribe."""
    selected = selected or set()
    topics = [
        ("general", "💻 All Jobs"),
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
        ("egypt", "🇪🇬 Egypt"),
        ("saudi", "🇸🇦 Saudi"),
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


LOCATION_OPTIONS = [
    ("remote", "🌍 Remote Only"),
    ("EG", "🇪🇬 Egypt"),
    ("SA", "🇸🇦 Saudi Arabia"),
    ("AE", "🇦🇪 UAE"),
    ("US", "🇺🇸 USA"),
    ("GB", "🇬🇧 UK"),
    ("DE", "🇩🇪 Germany"),
    ("CA", "🇨🇦 Canada"),
    ("NL", "🇳🇱 Netherlands"),
    ("IN", "🇮🇳 India"),
    ("FR", "🇫🇷 France"),
    ("PL", "🇵🇱 Poland"),
    ("TR", "🇹🇷 Turkey"),
]


def location_selection_keyboard(selected: set[str] = None) -> InlineKeyboardMarkup:
    """Build location selection keyboard for /subscribe."""
    selected = selected or set()
    buttons = []
    row = []
    for key, label in LOCATION_OPTIONS:
        check = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(
            f"{check}{label}",
            callback_data=f"sub_location:{key}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✅ Done (or skip)", callback_data="sub_location_done")])
    return InlineKeyboardMarkup(buttons)


SOURCE_OPTIONS = [
    ("linkedin", "LinkedIn"),
    ("indeed", "Indeed"),
    ("glassdoor", "Glassdoor"),
    ("remotive", "Remotive"),
    ("remoteok", "RemoteOK"),
    ("wwr", "We Work Remotely"),
    ("himalayas", "Himalayas"),
    ("arbeitnow", "Arbeitnow"),
    ("jobicy", "Jobicy"),
    ("workingnomads", "Working Nomads"),
    ("adzuna", "Adzuna"),
    ("themuse", "The Muse"),
    ("jooble", "Jooble"),
    ("reed", "Reed"),
    ("findwork", "Findwork"),
    ("usajobs", "USAJobs"),
    ("devitjobs", "DevITjobs"),
    ("greenhouse", "Greenhouse"),
    ("lever", "Lever"),
    ("workable", "Workable"),
    ("recruitee", "Recruitee"),
    ("ashby", "Ashby"),
    ("smartrecruiters", "SmartRecruiters"),
]


def source_selection_keyboard(selected: set[str] = None) -> InlineKeyboardMarkup:
    """Build source/provider selection keyboard for /subscribe."""
    selected = selected or set()
    buttons = []
    row = []
    for key, label in SOURCE_OPTIONS:
        check = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(
            f"{check}{label}",
            callback_data=f"sub_source:{key}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✅ Done (or skip for all)", callback_data="sub_source_done")])
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


def alerts_unsub_keyboard(alerts: list[dict]) -> InlineKeyboardMarkup:
    """Chooser shown by /unsubscribe — one row per alert plus All / Cancel."""
    buttons = []
    for a in alerts:
        position = a["position"]
        label = _alert_short_label(a)
        buttons.append([InlineKeyboardButton(
            f"Alert #{position} — {label}",
            callback_data=f"unsub:{position}",
        )])
    buttons.append([InlineKeyboardButton(
        "— Remove all alerts —",
        callback_data="unsub:all",
    )])
    buttons.append([InlineKeyboardButton(
        "Cancel",
        callback_data="unsub:cancel",
    )])
    return InlineKeyboardMarkup(buttons)


def alert_card_keyboard(position: int, dm_enabled: bool) -> InlineKeyboardMarkup:
    """Per-alert action row in /mysubs: Edit / Delete / DM toggle."""
    dm_label = "🔔 DM On" if dm_enabled else "🔕 DM Off"
    dm_target = "off" if dm_enabled else "on"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✏ Edit #{position}", callback_data=f"edit:{position}"),
        InlineKeyboardButton(f"🗑 Delete #{position}", callback_data=f"del:{position}"),
        InlineKeyboardButton(dm_label, callback_data=f"dm:{position}:{dm_target}"),
    ]])


def confirm_remove_all_keyboard() -> InlineKeyboardMarkup:
    """Confirmation prompt shown before bulk-deleting all alerts."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, delete all", callback_data="unsub:all_confirm"),
        InlineKeyboardButton("Cancel", callback_data="unsub:cancel"),
    ]])


def _alert_short_label(alert: dict) -> str:
    """Compose a short human-readable label for an alert (used in chooser rows)."""
    parts = []
    topics = alert.get("topics") or []
    if topics:
        parts.append(", ".join(topics[:3]) + ("…" if len(topics) > 3 else ""))
    seniority = alert.get("seniority") or []
    if seniority:
        parts.append("/".join(seniority))
    locations = alert.get("locations") or []
    if locations:
        parts.append("/".join(locations[:3]))
    return " · ".join(parts) if parts else "all jobs"
