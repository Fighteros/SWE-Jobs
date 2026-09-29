"""Tests for subscription-builder topic selection behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot.callbacks import _handle_sub_topic


def _select_topic(selected: set[str], topic: str) -> set[str]:
    context = SimpleNamespace(user_data={"sub_topics": selected})
    query = MagicMock()
    query.edit_message_reply_markup = AsyncMock()
    asyncio.run(_handle_sub_topic(query, None, context, f"sub_topic:{topic}"))
    return context.user_data["sub_topics"]


def test_selecting_general_clears_specific_topics():
    assert _select_topic({"fullstack", "backend"}, "general") == {"general"}


def test_selecting_specific_topic_clears_general():
    assert _select_topic({"general"}, "fullstack") == {"fullstack"}


def test_general_can_be_deselected():
    assert _select_topic({"general"}, "general") == set()
