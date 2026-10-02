# ADR 0004: Job Lifecycle and Queue Safety

Date: 2026-10-02
Status: Accepted (planned — implementation in Milestone 2)

## Context

The durable delivery queue (`job_deliveries`, migration 007) decoupled
ingestion from delivery, but several correctness issues remain: job publication
state, archive behavior, queue replay safety, worker fencing, atomic enqueue,
ingestion locking, and durable broadcasts. High-risk admin controls (delete,
archive, replay, broadcast) must not be exposed before these are fixed.

## Decision

1. Fix job lifecycle and queue safety **before** exposing privileged write
   controls in the dashboard.
2. Scope of fixes (Milestone 2):
   - Job publication state (consistent `sent_at` / delivery status).
   - Archive behavior (safe move from `jobs` to `jobs_archive`).
   - Queue replay correctness (idempotent, audit-logged).
   - Worker fencing (no double-processing across restarts).
   - Atomic enqueue (single transaction for job + deliveries).
   - Ingestion locking (no overlapping fetch cycles).
   - Durable broadcasts (broadcast records that survive restarts).
3. Only after Milestone 2 passes do later milestones add admin mutations that
   touch these surfaces.

## Consequences

- Admin modules that mutate jobs/deliveries/broadcasts are gated behind the
  queue-safety milestone.
- Read-only admin modules (Milestone 8) can ship earlier because they do not
  depend on write correctness.
