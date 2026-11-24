import asyncio
from unittest.mock import patch

import pytest

from bot import imessage_commands


USER = {"id": 7, "telegram_id": -42, "username": "+201099599616"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _user():
    with patch("bot.imessage_commands.db.get_or_create_imessage_user", return_value=USER):
        yield


def test_help():
    reply = run(imessage_commands.handle_inbound("+201099599616", "/help"))
    assert "/alert add" in reply


def test_unknown_command():
    reply = run(imessage_commands.handle_inbound("+201099599616", "hello there"))
    assert "/help" in reply


def test_alert_add_saves_valid_alert():
    with patch("bot.imessage_commands.db.create_user_alert", return_value=99) as create, \
         patch("bot.imessage_commands.db.get_user_alerts", return_value=[
             {"position": 1, "topics": ["backend"], "seniority": ["mid"],
              "locations": ["remote"], "sources": [], "keywords": ["python"],
              "min_salary": 60000, "dm_enabled": True},
         ]):
        reply = run(imessage_commands.handle_inbound(
            "+201099599616",
            "/alert add topics=backend seniority=mid locations=remote keywords=python min_salary=60000",
        ))

    alert = create.call_args.args[1]
    assert alert["topics"] == ["backend"]
    assert alert["seniority"] == ["mid"]
    assert alert["locations"] == ["remote"]
    assert alert["keywords"] == ["python"]
    assert alert["min_salary"] == 60000
    assert "Alert #1 saved" in reply


def test_alert_add_requires_topics():
    with patch("bot.imessage_commands.db.create_user_alert") as create:
        reply = run(imessage_commands.handle_inbound(
            "+201099599616", "/alert add seniority=mid"
        ))
    create.assert_not_called()
    assert "topics is required" in reply


def test_alert_add_rejects_unknown_topic():
    reply = run(imessage_commands.handle_inbound(
        "+201099599616", "/alert add topics=backend,notatopic"
    ))
    assert "Unknown topics: notatopic" in reply


def test_alert_add_rejects_unknown_seniority_and_location():
    reply = run(imessage_commands.handle_inbound(
        "+201099599616", "/alert add topics=backend seniority=boss"
    ))
    assert "Unknown seniority: boss" in reply

    reply = run(imessage_commands.handle_inbound(
        "+201099599616", "/alert add topics=backend locations=ZZ"
    ))
    assert "Unknown locations: ZZ" in reply


def test_alert_add_normalizes_case():
    with patch("bot.imessage_commands.db.create_user_alert", return_value=1) as create, \
         patch("bot.imessage_commands.db.get_user_alerts", return_value=[
             {"position": 1, "topics": ["backend"], "dm_enabled": True},
         ]):
        run(imessage_commands.handle_inbound(
            "+201099599616", "/alert add topics=BACKEND locations=eg,remote"
        ))
    alert = create.call_args.args[1]
    assert alert["topics"] == ["backend"]
    assert alert["locations"] == ["EG", "remote"]


def test_alerts_empty_and_list():
    with patch("bot.imessage_commands.db.get_user_alerts", return_value=[]):
        reply = run(imessage_commands.handle_inbound("+201099599616", "/alerts"))
    assert "no alerts" in reply.lower()

    with patch("bot.imessage_commands.db.get_user_alerts", return_value=[
        {"position": 1, "topics": ["backend", "ai_ml"], "dm_enabled": True},
        {"position": 2, "topics": ["general"], "dm_enabled": False},
    ]):
        reply = run(imessage_commands.handle_inbound("+201099599616", "/alerts"))
    assert "Your alerts (2)" in reply
    assert "#1" in reply and "#2" in reply
    assert "paused" in reply


def test_alert_remove_and_remove_all():
    with patch("bot.imessage_commands.db.delete_user_alert", return_value=True) as delete:
        reply = run(imessage_commands.handle_inbound("+201099599616", "/alert remove 2"))
    delete.assert_called_once_with(USER["id"], 2)
    assert "removed" in reply

    with patch("bot.imessage_commands.db.delete_all_user_alerts", return_value=3) as delete_all:
        reply = run(imessage_commands.handle_inbound("+201099599616", "/unsubscribe all"))
    delete_all.assert_called_once_with(USER["id"])
    assert "all 3" in reply


def test_alert_remove_missing_position():
    with patch("bot.imessage_commands.db.delete_user_alert", return_value=False):
        reply = run(imessage_commands.handle_inbound("+201099599616", "/alert remove 9"))
    assert "No alert #9" in reply


def test_alert_pause_and_resume():
    with patch("bot.imessage_commands.db.set_alert_dm_enabled", return_value=True) as set_dm:
        reply = run(imessage_commands.handle_inbound("+201099599616", "/alert pause 1"))
    set_dm.assert_called_once_with(USER["id"], 1, False)
    assert "paused" in reply

    with patch("bot.imessage_commands.db.set_alert_dm_enabled", return_value=True) as set_dm:
        reply = run(imessage_commands.handle_inbound("+201099599616", "/alert resume 1"))
    set_dm.assert_called_once_with(USER["id"], 1, True)
    assert "resumed" in reply
