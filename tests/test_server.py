"""
Tests for server.py scheduler separation.
"""

import asyncio
from unittest.mock import patch, AsyncMock

import pytest

import server


@pytest.mark.asyncio
async def test_fetch_loop_runs_pipeline_and_sleeps():
    with patch("server.FETCH_INTERVAL_MINUTES", 0), \
         patch("main.main", new_callable=AsyncMock) as mock_main:
        # Cancel the loop after one iteration.
        task = asyncio.create_task(server._job_fetch_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert mock_main.called


@pytest.mark.asyncio
async def test_fetch_loop_skips_when_previous_still_running():
    lock_held = asyncio.Event()
    can_release = asyncio.Event()

    async def slow_pipeline():
        lock_held.set()
        await can_release.wait()

    with patch("main.main", side_effect=slow_pipeline):
        async with server._fetch_lock:
            task = asyncio.create_task(server._job_fetch_loop())
            # Give the task a chance to see the held lock.
            await asyncio.sleep(0.05)
            # The loop should detect the lock is held and skip without awaiting main.
            assert not lock_held.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_delivery_loop_skips_when_previous_still_running():
    async with server._delivery_lock:
        with patch("server.TELEGRAM_BOT_TOKEN", "dummy"), \
             patch("server.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot
            mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
            mock_bot.__aexit__ = AsyncMock(return_value=False)
            task = asyncio.create_task(server._delivery_loop())
            # Give the task a chance to see the held lock.
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
