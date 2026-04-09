"""
One-time migration: import seen_jobs.json URLs into the jobs table.
This prevents re-sending jobs that were already sent in v1.

Usage:
  1. Checkout the data branch: git checkout origin/data -- seen_jobs.json
  2. Run: python scripts/migrate_seen_jobs.py
  3. Delete seen_jobs.json when done
"""

import json
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


def main():
    seen_file = "seen_jobs.json"

    try:
        with open(seen_file, "r", encoding="utf-8") as f:
            seen_ids = json.load(f)
    except FileNotFoundError:
        log.error(f"{seen_file} not found. Fetch it from the data branch first.")
        sys.exit(1)

    if not isinstance(seen_ids, list):
        log.error(f"Expected a JSON array, got {type(seen_ids)}")
        sys.exit(1)

    log.info(f"Found {len(seen_ids)} seen job IDs to migrate")

    from core import db

    inserted = 0
    skipped = 0
    for uid in seen_ids:
        if not uid or not isinstance(uid, str):
            skipped += 1
            continue

        # Insert minimal row — just enough to prevent re-sending
        try:
            result = db._execute(
                """INSERT INTO jobs (unique_id, title, company, location, url, source, sent_at)
                   VALUES (%s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT (unique_id) DO NOTHING
                   RETURNING id""",
                (uid, "Migrated from v1", "", "", uid if uid.startswith("http") else "", "v1_migration"),
            )
            if result:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            log.warning(f"Failed to insert {uid[:50]}: {e}")
            skipped += 1

    log.info(f"Migration complete: {inserted} inserted, {skipped} skipped (of {len(seen_ids)} total)")


if __name__ == "__main__":
    main()
