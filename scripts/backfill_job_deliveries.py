#!/usr/bin/env python3
"""
Backfill existing unsent jobs into the durable delivery queue.

Run once after deploying migration 007_job_deliveries.sql:

    python scripts/backfill_job_deliveries.py

The migration already creates group_topic records for unsent jobs; this script
ensures subscriber-DM records are created for all jobs that match current
subscribers and alerts. It is idempotent and safe to re-run.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logging_config import setup_logging
from core.delivery_queue import backfill_unsent_jobs

setup_logging()
log = logging.getLogger(__name__)


async def main():
    log.info("Starting backfill of unsent jobs into job_deliveries")
    stats = await asyncio.to_thread(backfill_unsent_jobs)
    log.info(
        f"Backfill complete: {stats['group_topic_backfilled']} group-topic, "
        f"{stats['subscriber_dm_backfilled']} subscriber-DM"
    )


if __name__ == "__main__":
    asyncio.run(main())
