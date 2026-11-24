"""
bot/imessage_commands.py — text command handling for iMessage users.

iMessage has no bot keyboards, so the alert-management flow is plain text.
The sidecar forwards inbound iMessages to POST /imessage/inbound, which calls
handle_inbound(); the returned text is sent back as the reply.

Commands:
  /start, /help                     — usage
  /alerts                           — list your alerts
  /alert add seniority=.. locations=.. sources=.. keywords=.. min_salary=..
                                    — create an alert (all filters optional)
  /alert remove N | all             — delete alert #N (or every alert)
  /alert pause N                    — stop DMs for alert #N
  /alert resume N                   — resume DMs for alert #N

Filters reuse the exact same user_alerts rows and matching logic as the
Telegram bot, so an iMessage user gets the same personalized delivery.
"""

import asyncio
import logging

from core import db
from bot.keyboards import LOCATION_OPTIONS, SOURCE_OPTIONS

log = logging.getLogger(__name__)

# The iMessage flow has no topics/groups/channels: alerts internally carry
# the existing {"general"} wildcard (see core.subscription_matching), so every
# job is a candidate and the remaining filters decide the match.
VALID_SENIORITY = {"intern", "junior", "mid", "senior", "lead", "executive"}
VALID_LOCATIONS = {key for key, _ in LOCATION_OPTIONS}
VALID_SOURCES = {key for key, _ in SOURCE_OPTIONS}

HELP_TEXT = """👋 SWE-Jobs over iMessage

I send you only the jobs that match your saved alerts.

/alert add seniority=mid,senior locations=remote,EG keywords=python min_salary=60000
  Create an alert. All filters are optional.
/alerts
  Show your alerts.
/alert remove 2
  Delete alert #2 ("all" removes every alert).
/alert pause 1 · /alert resume 1
  Pause/resume delivery for an alert.
/help
  This message.

seniority: intern, junior, mid, senior, lead, executive
locations: remote, EG, SA, AE, US, GB, DE, CA, NL, IN, FR, PL, TR
sources: linkedin, indeed, glassdoor, remotive, remoteok, wwr, himalayas, arbeitnow, jobicy, workingnomads, adzuna, themuse, jooble, reed, findwork, usajobs, devitjobs, greenhouse, lever, workable, recruitee, ashby, smartrecruiters"""


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _invalid(values: list[str], valid: set) -> list[str]:
    return [v for v in values if v not in valid]


def _parse_add_args(args: list[str]) -> tuple[dict | None, str | None]:
    """
    Parse key=value tokens into an alert dict.
    Returns (alert, error_message); exactly one is not None.
    """
    alert: dict = {
        "topics": ["general"], "seniority": [], "locations": [],
        "sources": [], "keywords": [], "min_salary": None,
    }
    seen: set[str] = set()
    for token in args:
        if "=" not in token:
            return None, f"Did not understand '{token}'. Use key=value pairs, e.g. seniority=mid locations=remote"
        key, _, value = token.partition("=")
        key = key.strip().lower()
        if key in seen:
            return None, f"'{key}' given twice."
        seen.add(key)
        if key == "topics":
            return None, "The iMessage bot has no topics — just drop that part. Example: /alert add seniority=mid locations=remote"
        elif key == "seniority":
            levels = [s.lower() for s in _split_csv(value)]
            bad = _invalid(levels, VALID_SENIORITY)
            if bad:
                return None, f"Unknown seniority: {', '.join(bad)}"
            alert["seniority"] = levels
        elif key == "locations":
            locs = [l if l == "remote" else l.upper() for l in _split_csv(value)]
            bad = _invalid(locs, VALID_LOCATIONS)
            if bad:
                return None, f"Unknown locations: {', '.join(bad)}"
            alert["locations"] = locs
        elif key == "sources":
            sources = [s.lower() for s in _split_csv(value)]
            bad = _invalid(sources, VALID_SOURCES)
            if bad:
                return None, f"Unknown sources: {', '.join(bad)}"
            alert["sources"] = sources
        elif key == "keywords":
            alert["keywords"] = _split_csv(value)
        elif key == "min_salary":
            try:
                salary = int(value.replace(",", "").replace("$", ""))
                if salary <= 0:
                    raise ValueError
                alert["min_salary"] = salary
            except ValueError:
                return None, f"min_salary must be a positive number, got '{value}'."
        else:
            return None, f"Unknown option '{key}'. Options: seniority, locations, sources, keywords, min_salary"
    return alert, None


def _describe_alert(a: dict) -> str:
    lines = [f"#{a['position']}"]
    # topics are not shown: iMessage alerts always carry the internal
    # {"general"} wildcard, which is not a user-facing filter here.
    if a.get("seniority"):
        lines.append(f"seniority: {', '.join(a['seniority'])}")
    if a.get("locations"):
        lines.append(f"locations: {', '.join(a['locations'])}")
    if a.get("sources"):
        lines.append(f"sources: {', '.join(a['sources'])}")
    if a.get("keywords"):
        lines.append(f"keywords: {', '.join(a['keywords'])}")
    if a.get("min_salary"):
        lines.append(f"min salary: ${a['min_salary']:,}/year")
    lines.append("delivery: " + ("on 🔔" if a.get("dm_enabled", True) else "paused 🔕"))
    return "\n".join(lines)


async def handle_inbound(address: str, text: str) -> str:
    """
    Handle one inbound iMessage from `address` and return the reply text.
    Auto-registers the sender as an iMessage user on first contact.
    """
    user = await asyncio.to_thread(db.get_or_create_imessage_user, address)
    text = (text or "").strip()
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:]

    if cmd in ("/start", "/help"):
        return HELP_TEXT

    if cmd == "/alerts":
        alerts = await asyncio.to_thread(db.get_user_alerts, user["id"])
        if not alerts:
            return "You have no alerts yet. Create one with:\n/alert add seniority=mid locations=remote"
        cards = "\n\n".join(_describe_alert(a) for a in alerts)
        return f"📋 Your alerts ({len(alerts)}):\n\n{cards}"

    if cmd == "/unsubscribe":
        args = ["remove"] + args
        cmd = "/alert"

    if cmd != "/alert":
        return "Sorry, I did not understand that. Send /help to see what I can do."

    if not args:
        return "Usage: /alert add ... · /alert remove N|all · /alert pause N · /alert resume N\n/help for details."

    sub = args[0].lower()
    sub_args = args[1:]

    if sub == "add":
        alert, error = _parse_add_args(sub_args)
        if error:
            return f"⚠️ {error}"
        await asyncio.to_thread(db.create_user_alert, user["id"], alert)
        alerts = await asyncio.to_thread(db.get_user_alerts, user["id"])
        position = alerts[-1]["position"] if alerts else 1
        return (
            f"✅ Alert #{position} saved:\n\n{_describe_alert(alerts[-1])}\n\n"
            "You'll get matching new jobs here on iMessage."
        )

    if sub in ("remove", "delete"):
        if not sub_args:
            return "Usage: /alert remove N  (or: /alert remove all)"
        if sub_args[0].lower() == "all":
            count = await asyncio.to_thread(db.delete_all_user_alerts, user["id"])
            return f"🗑 Removed all {count} alert(s). You will no longer receive job matches."
        try:
            position = int(sub_args[0])
        except ValueError:
            return f"⚠️ '{sub_args[0]}' is not an alert number. Send /alerts to see your alerts."
        ok = await asyncio.to_thread(db.delete_user_alert, user["id"], position)
        if ok:
            return f"🗑 Alert #{position} removed."
        return f"⚠️ No alert #{position}. Send /alerts to see your alerts."

    if sub in ("pause", "resume"):
        if not sub_args:
            return f"Usage: /alert {sub} N"
        try:
            position = int(sub_args[0])
        except ValueError:
            return f"⚠️ '{sub_args[0]}' is not an alert number. Send /alerts to see your alerts."
        enabled = sub == "resume"
        ok = await asyncio.to_thread(db.set_alert_dm_enabled, user["id"], position, enabled)
        if ok:
            return f"{'▶️' if enabled else '⏸'} Alert #{position} {'resumed' if enabled else 'paused'}."
        return f"⚠️ No alert #{position}. Send /alerts to see your alerts."

    return f"⚠️ Unknown /alert action '{sub}'. Usage: /alert add ... · /alert remove N|all · /alert pause N · /alert resume N"
