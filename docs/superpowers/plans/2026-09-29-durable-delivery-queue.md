# Plan: Durable Job-Delivery Queue

**Date:** 2026-09-29  
**Branch:** `feat/durable-job-delivery-queue`  
**Status:** Implemented

## Goal

Make job delivery durable, decoupled from ingestion, and lossless:

- Every fetched/inserted job must eventually be handled.
- The old 50-job send cap must not permanently drop jobs.
- Fetching and delivery run on independent schedules and may overlap.
- Delivery state is tracked per topic and per subscriber.
- Failed deliveries retry with backoff; permanent failures go to a dead-letter state.

## Decisions

- **Queue backend:** PostgreSQL only. No Redis, RabbitMQ, SQS, or in-memory queue as source of truth.
- **Fetch cadence:** remains every 5 minutes (`FETCH_INTERVAL_MINUTES=5`).
- **Delivery cadence:** every 60 seconds (`DELIVERY_INTERVAL_SECONDS=60`).
- **Schema:** `job_deliveries` table with status, attempts, errors, timestamps, worker ID, message ID, and dead-letter reason.
- **Backfill:** Migration creates group-topic records for existing unsent jobs; `scripts/backfill_job_deliveries.py` creates subscriber-DM records.
- **Claiming:** `FOR UPDATE SKIP LOCKED` on due pending records.
- **Recovery:** Stale `processing` records are returned to pending or dead-lettered after the lease expires.
- **Retry:** 5 attempts, base 30s, exponential backoff.
- **Dead-letter replay:** `core.delivery_queue.replay_dead_letter(id)`.
- **Seed mode:** delivery records are created but marked `skipped` with reason `seed_mode`.

## Files Changed

- `supabase/migrations/007_job_deliveries.sql`
- `core/config.py`
- `core/delivery_queue.py`
- `core/delivery_scheduler.py`
- `core/subscription_matching.py`
- `core/monitoring.py`
- `bot/sender.py`
- `bot/notifications.py`
- `main.py`
- `server.py`
- `scripts/backfill_job_deliveries.py`
- `.env.example`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CONFIGURATION.md`
- `tests/test_delivery_queue.py`
- `tests/test_delivery_queue_integration.py`
- `tests/test_delivery_scheduler.py`
- `tests/test_migration_007.py`
- `tests/test_config.py`
- `tests/test_server.py`
- `tests/test_notifications.py`

## Deployment Notes

1. Apply migration `007_job_deliveries.sql`.
2. Run `python scripts/backfill_job_deliveries.py` once to create subscriber-DM records for unsent jobs.
3. Restart the backend service to start the independent fetch and delivery schedulers.
4. Monitor `job_deliveries` status counts and dead-letter records.
