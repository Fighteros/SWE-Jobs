# Multi-Alert Subscriptions — Design

**Date:** 2026-04-25
**Status:** Approved, ready for implementation plan
**Branch:** `claude/festive-thompson-0ae015`

## Problem

Each Telegram user can currently have only **one** alert/subscription. Once the user runs `/subscribe`, every later run overwrites the previous configuration. The schema enforces this with `UNIQUE(telegram_id)` on `users` and a single JSONB blob in `users.subscriptions`. There is also no way to remove individual alerts — `/unsubscribe` clears the one alert that exists.

Users have asked for the ability to maintain multiple independent alerts (e.g., *"Senior Backend in Egypt"* and *"Junior Data, remote"*) and to remove them individually or all at once.

## Goals

1. Each user can hold multiple independent alerts.
2. Each alert has its own filters (topics, seniority, locations, sources, keywords, min salary) and its own DM-on/off toggle.
3. Users can list all their alerts, edit any of them, delete one, or delete all.
4. Existing single-subscription users keep their current alert with no action required.

## Non-goals

- No per-alert rate limiting (the existing 20-DMs/user/hour cap stays per-user).
- No user-provided alert names — alerts are identified by a stable 1-based number (`Alert #1`, `Alert #2`, …).
- No cap on alert count for now (unlimited).
- No REST API surface for alerts (the `api/` package does not expose subscriptions today; out of scope).

## Architecture

A new `user_alerts` table holds one row per alert. The legacy `users.subscriptions` JSONB column is migrated into `user_alerts` rows during the schema migration and dropped in a follow-up migration after one safe deploy cycle.

The bot's `/subscribe`, `/unsubscribe`, and `/mysubs` commands switch from operating on a single JSONB blob to operating on a list. The notification matcher loops over each user's alerts and emits at most one DM per matched job (first-match wins).

## Database schema

**New table** (`supabase/migrations/005_user_alerts.sql`):

```sql
CREATE TABLE IF NOT EXISTS user_alerts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    topics        TEXT[]  DEFAULT '{}',
    seniority     TEXT[]  DEFAULT '{}',
    locations     TEXT[]  DEFAULT '{}',
    sources       TEXT[]  DEFAULT '{}',
    keywords      TEXT[]  DEFAULT '{}',
    min_salary    INTEGER,
    dm_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, position)
);

CREATE INDEX idx_user_alerts_user_id ON user_alerts(user_id);
```

**Design choices:**
- `TEXT[]` for filter fields (instead of JSONB) — flat lists, easier to query, native array operators (`&&` overlap) available if matching ever moves into SQL.
- `position` with `UNIQUE(user_id, position)` — guarantees stable numbering for `/mysubs`. When an alert is deleted, the same transaction re-packs higher positions down by one so the user's mental model stays contiguous.
- `dm_enabled` per alert — replaces the role of `users.notify_dm` for matching. `notify_dm` is retained as a global kill switch.
- `ON DELETE CASCADE` — alerts disappear with their user.

**Data migration (same SQL file):**

```sql
INSERT INTO user_alerts (user_id, position, topics, seniority, locations, sources, keywords, min_salary, dm_enabled)
SELECT
    u.id,
    1,
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'topics')),    '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'seniority')), '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'locations')), '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'sources')),   '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'keywords')),  '{}'),
    NULLIF((u.subscriptions->>'min_salary')::int, 0),
    TRUE  -- per-alert DM defaults on; users.notify_dm remains the separate global kill switch
FROM users u
WHERE u.subscriptions IS NOT NULL AND u.subscriptions <> '{}'::jsonb;
```

`users.subscriptions` is **not** dropped here — that happens in a follow-up migration `006_drop_users_subscriptions.sql` after Step 2 is stable in production.

## Data layer (`core/db.py`)

The legacy `update_user_subscriptions(user_id, subscriptions)` is removed. New API:

```python
def get_user_alerts(user_id: int) -> list[dict]:
    """All alerts for a user, ordered by position."""

def get_user_alert(user_id: int, position: int) -> dict | None:
    """One alert by 1-based position."""

def create_user_alert(user_id: int, alert: dict) -> int:
    """Insert at next available position. Returns new alert id."""

def update_user_alert(user_id: int, position: int, alert: dict) -> bool:
    """Replace filter fields on an existing alert."""

def set_alert_dm_enabled(user_id: int, position: int, enabled: bool) -> bool:
    """Toggle the DM flag for a single alert."""

def delete_user_alert(user_id: int, position: int) -> bool:
    """Delete one alert; in same TX, decrement position for higher-numbered alerts."""

def delete_all_user_alerts(user_id: int) -> int:
    """Delete every alert for the user. Returns count removed."""
```

Returns are plain `dict` (matches existing pattern in `core/db.py`). Single-transaction delete + re-pack avoids any window of non-contiguous positions.

## Bot commands (`bot/commands.py`, `bot/callbacks.py`)

**`/subscribe`** — same 4-step wizard (topics → seniority → locations → sources). The final handler `_handle_sub_source_done` calls `db.create_user_alert(user.id, payload)` instead of overwriting. New alerts default to `dm_enabled=True`.

**`/unsubscribe`** — shows an inline-keyboard chooser:

```
Which alert do you want to remove?

[ Alert #1 — Backend, Senior, Remote ]
[ Alert #2 — DevOps, Mid, EG/SA       ]
[ Alert #3 — Data, Junior, Remote     ]
[ — Remove all alerts —               ]
[ Cancel                              ]
```

Per-row callbacks: `unsub:<n>`, `unsub:all`, `unsub:cancel`. The label suffix after `Alert #N — …` is auto-composed from the alert's filters and is purely informational (the identifier is the number).

**`/mysubs`** — replaces the single-block readout with one card per alert:

```
Your alerts (3):

#1 — Topics: Backend · Seniority: Senior · Locations: Remote
[ ✏ Edit #1 ] [ 🗑 Delete #1 ] [ 🔔 DM On ]

#2 — Topics: DevOps · Seniority: Mid · Locations: EG, SA
[ ✏ Edit #2 ] [ 🗑 Delete #2 ] [ 🔕 DM Off ]

#3 — ...
```

Empty state: *"You have no alerts. Run /subscribe to create one."*

**Callback families:**

| Callback                  | Action                                                                                                       |
|---------------------------|--------------------------------------------------------------------------------------------------------------|
| `unsub:<n>`               | `db.delete_user_alert(user_id, n)`; reply with remaining count.                                              |
| `unsub:all`               | Confirmation prompt → `db.delete_all_user_alerts(user_id)`. Bulk delete is the only confirm-gated action.    |
| `unsub:cancel`            | Dismiss without changes.                                                                                     |
| `del:<n>`                 | Same as `unsub:<n>` but re-renders `/mysubs` in place after delete.                                          |
| `dm:<n>:<on\|off>`        | `db.set_alert_dm_enabled(...)`; edit the message in place to flip the button label.                          |
| `edit:<n>`                | Re-enters the 4-step wizard with `context.user_data["edit_position"] = n` and pre-seeded filters; final step calls `db.update_user_alert` instead of `create_user_alert`. |

**Why this shape:**
- Edit reuses the wizard rather than building a parallel "edit one field" flow — fewer moving parts, ships sooner.
- Per-alert delete and DM toggle are reversible (re-create / re-toggle) so they fire on a single tap. Bulk delete isn't reversible, so it gets a confirmation step.
- DM toggle uses `editMessageText` so repeated taps don't spam the chat.

## Notification matching (`bot/notifications.py`)

`_job_matches_subscription` is renamed `_job_matches_alert` (signature `alert: dict` instead of `subs: dict`). The match logic — AND across filter groups, OR within each group — is unchanged.

The per-user loop becomes per-alert:

```python
for user in users_to_notify:
    if not user.notify_dm:
        continue
    alerts = db.get_user_alerts(user.id)
    matched_alert = None
    for alert in alerts:
        if not alert["dm_enabled"]:
            continue
        if _job_matches_alert(job, alert):
            matched_alert = alert
            break  # first-match wins; one DM per (user, job) pair
    if matched_alert is None:
        continue
    if _is_blacklisted(job, user.blacklist):
        continue
    # rate-limit check (unchanged: 20/user/hour)
    send_dm(user, job, matched_alert)
```

**Behavior contract:**
- A job matching multiple alerts of the same user produces exactly **one** DM (first-match wins).
- An alert with `dm_enabled=False` is skipped during matching but remains visible in `/mysubs`.
- Global `users.notify_dm=False` suppresses **all** alerts for that user (kill switch).
- Per-user blacklist is applied once after a match, not per alert.
- Rate limit stays per-user at 20 DMs/hour; not per-alert.

## Rollout

The change is sequenced so `main` is deployable at every step.

**Step 1 — schema migration only.** Apply `005_user_alerts.sql`. Both `users.subscriptions` and `user_alerts` coexist; no code reads `user_alerts` yet.

**Step 2 — code change (single PR).** Update `core/db.py`, `bot/commands.py`, `bot/callbacks.py`, `bot/notifications.py`, plus tests. All reads switch to `user_alerts`; the legacy `update_user_subscriptions()` is removed; `users.subscriptions` is no longer read or written.

**Step 3 — drop legacy column (follow-up PR).** After Step 2 has been live for at least one full bot run cycle (a day of soak in practice), ship `006_drop_users_subscriptions.sql` to `ALTER TABLE users DROP COLUMN subscriptions`.

The split between Steps 2 and 3 preserves a rollback target. If Step 2 has a bug we missed, the legacy column still holds the data we need to revert.

## Testing

**`tests/test_db.py`** (extend):
- Create / get / delete / update alert basics.
- Re-pack invariant: after deleting alert #2 from a list of three, the remaining alerts have positions `[1, 2]` (not `[1, 3]`).
- `set_alert_dm_enabled` round-trip.
- `delete_all_user_alerts` returns correct count.

**`tests/test_notifications.py`** (extend):
- A user with two alerts where the job matches both → exactly one DM.
- A user whose only matching alert has `dm_enabled=False` → no DM.
- A migrated user (single legacy subscription → single alert at position 1) keeps getting matched.
- Global `notify_dm=False` suppresses DMs even when alerts match.

**`tests/test_migration_005.py`** (new):
- Fixture user with `users.subscriptions = {topics: [...], seniority: [...], ...}` produces exactly one `user_alerts` row with `position=1` and the same filter values.
- Fixture user with `subscriptions = '{}'::jsonb` produces zero `user_alerts` rows.

## Affected files

| File                                        | Change                                                                                |
|---------------------------------------------|---------------------------------------------------------------------------------------|
| `supabase/migrations/005_user_alerts.sql`   | New: create table, indexes, data migration from `users.subscriptions`.                |
| `supabase/migrations/006_drop_users_subscriptions.sql` | New (follow-up PR): drop the legacy column.                                |
| `core/db.py`                                | Replace `update_user_subscriptions` with the seven new alert CRUD functions.          |
| `bot/commands.py`                           | `/subscribe`, `/unsubscribe`, `/mysubs` updated for multi-alert UX.                   |
| `bot/callbacks.py`                          | New callback families (`unsub:*`, `del:*`, `dm:*`, `edit:*`); subscribe wizard reused. |
| `bot/notifications.py`                      | Per-alert match loop; rename `_job_matches_subscription` → `_job_matches_alert`.       |
| `tests/test_db.py`                          | Extend with alert CRUD tests including re-pack invariant.                              |
| `tests/test_notifications.py`               | Extend with multi-alert scenarios.                                                     |
| `tests/test_migration_005.py`               | New: assert legacy → `user_alerts` migration correctness.                              |

## Open questions

None — all questions resolved during brainstorming. Cap (unlimited), naming (numbered only), command split (separate `/subscribe` and `/unsubscribe`), migration (auto), and editing (yes, via `/mysubs`) are all decided.
