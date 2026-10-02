import asyncio
from unittest.mock import AsyncMock, patch

from core.monitoring import check_alerts


def test_check_alerts_ignores_dead_letter_deliveries():
    bot = object()
    run = {
        "jobs_fetched": 1,
        "finished_at": None,
        "started_at": None,
        "source_stats": {},
        "jobs_sent": 0,
    }

    async def fetchone(query, _params):
        if "FROM bot_runs" in query:
            return run
        if "status = 'dead_letter'" in query:
            return {"count": 1}
        return None

    async def run_check():
        with patch("core.monitoring.adb._fetchone", side_effect=fetchone), \
             patch("core.monitoring.adb._fetchall", return_value=[]), \
             patch("core.monitoring.send_admin_alert", new_callable=AsyncMock) as send_alert:
            alerts = await check_alerts(bot, run_id=1)

        assert alerts == []
        send_alert.assert_not_awaited()

    asyncio.run(run_check())
