# Multi-Alert Subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single per-user subscription (one JSONB blob in `users.subscriptions`) with a list of independent alerts stored in a new `user_alerts` table, so users can hold multiple alerts and add/edit/delete them individually or in bulk.

**Architecture:** Introduce a new `user_alerts` table with one row per alert (FK to `users.id`, 1-based `position`, per-alert filter columns, per-alert `dm_enabled`). The legacy `users.subscriptions` JSONB column is migrated into the new table during the schema migration and dropped in a follow-up migration. The Telegram bot's `/subscribe`, `/unsubscribe`, `/mysubs` commands switch from operating on a single dict to operating on a list, with new inline-keyboard callbacks for delete/edit/DM-toggle. The notification matcher loops per-alert (first-match wins) so each user gets at most one DM per matched job.

**Tech Stack:** Python 3.11+, psycopg2, python-telegram-bot, Supabase Postgres, pytest with mocks (existing pattern).

**Spec:** [docs/superpowers/specs/2026-04-25-multi-alert-subscriptions-design.md](../specs/2026-04-25-multi-alert-subscriptions-design.md)

---

## File Structure

**Create:**
- `supabase/migrations/005_user_alerts.sql` — new table, indexes, data migration from `users.subscriptions`.
- `tests/test_user_alerts.py` — unit tests for the seven new alert CRUD functions in `core/db.py` (mock-based, no DB).

**Modify:**
- `core/db.py` — remove `update_user_subscriptions`; add seven new alert CRUD functions.
- `bot/commands.py` — rewrite `cmd_unsubscribe` (chooser) and `cmd_mysubs` (per-alert cards). `cmd_subscribe` body stays the same.
- `bot/callbacks.py` — `_handle_sub_source_done` switches to `create_user_alert` / `update_user_alert`; add new callback families (`unsub:*`, `del:*`, `dm:*`, `edit:*`).
- `bot/keyboards.py` — add three new keyboard builders: `alerts_unsub_keyboard`, `alert_card_keyboard`, `confirm_remove_all_keyboard`.
- `bot/notifications.py` — rename `_job_matches_subscription` → `_job_matches_alert`; rewrite `notify_subscribers` to iterate per-alert with first-match wins.
- `tests/test_notifications.py` — rename existing tests to use `_job_matches_alert`; add multi-alert scenarios.

**Follow-up (not in this plan):**
- `supabase/migrations/006_drop_users_subscriptions.sql` — to ship after one safe deploy cycle.

---

## Task 1: Migration 005 — `user_alerts` table + data migration

**Files:**
- Create: `supabase/migrations/005_user_alerts.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- =============================================================================
-- Migration 005: user_alerts — multiple alerts per user
-- Replaces users.subscriptions (single JSONB) with a list of alert rows.
-- This migration creates the new table and copies existing data.
-- The users.subscriptions column is dropped in a follow-up migration (006)
-- after one safe deploy cycle.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_alerts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    topics        TEXT[]  NOT NULL DEFAULT '{}',
    seniority     TEXT[]  NOT NULL DEFAULT '{}',
    locations     TEXT[]  NOT NULL DEFAULT '{}',
    sources       TEXT[]  NOT NULL DEFAULT '{}',
    keywords      TEXT[]  NOT NULL DEFAULT '{}',
    min_salary    INTEGER,
    dm_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, position)
);

CREATE INDEX IF NOT EXISTS idx_user_alerts_user_id ON user_alerts (user_id);

-- Auto-update updated_at on UPDATE (uses helper from migration 001)
CREATE TRIGGER user_alerts_updated_at
    BEFORE UPDATE ON user_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE user_alerts ENABLE ROW LEVEL SECURITY;

-- Data migration: copy each user's existing subscriptions JSONB into a row.
-- Per-alert dm_enabled defaults to TRUE; users.notify_dm remains the global
-- kill switch and is independent.
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
    TRUE
FROM users u
WHERE u.subscriptions IS NOT NULL
  AND u.subscriptions <> '{}'::jsonb
  AND (u.subscriptions->'topics') IS NOT NULL;
```

- [ ] **Step 2: Verify the SQL parses (syntax check via psql or Supabase migration dry-run)**

Run (only if a local Postgres or supabase CLI is available; otherwise skip and rely on review):
```bash
psql -d postgres -f supabase/migrations/005_user_alerts.sql --set ON_ERROR_STOP=1
```
Expected: no errors. If only Supabase CLI is available: `supabase db lint` (or apply against a dev project).

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/005_user_alerts.sql
git commit -m "feat(db): add user_alerts table and migrate existing subscriptions"
```

---

## Task 2: `core/db.py` — `create_user_alert`

**Files:**
- Modify: `core/db.py` (add new section "User Alerts" after the "Users" section, around line 510)
- Create: `tests/test_user_alerts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_user_alerts.py`:

```python
"""
Tests for user_alerts CRUD in core/db.py — mock-based, no real DB.
"""
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# create_user_alert
# ---------------------------------------------------------------------------

class TestCreateUserAlert:
    def test_inserts_at_next_position_when_user_has_no_alerts(self):
        """First alert for a user gets position=1."""
        from core.db import create_user_alert

        with patch("core.db._fetchone") as mock_fetchone:
            # First call: max(position) lookup → no rows
            # Second call: INSERT ... RETURNING id → {"id": 42}
            mock_fetchone.side_effect = [{"max_pos": None}, {"id": 42}]

            alert_id = create_user_alert(
                user_id=7,
                alert={
                    "topics": ["backend"],
                    "seniority": ["senior"],
                    "locations": ["remote"],
                    "sources": [],
                    "keywords": [],
                    "min_salary": None,
                },
            )

            assert alert_id == 42
            # Verify the INSERT used position=1
            insert_call = mock_fetchone.call_args_list[1]
            params = insert_call[0][1]
            # Params: (user_id, position, topics, seniority, locations, sources, keywords, min_salary)
            assert params[0] == 7
            assert params[1] == 1

    def test_inserts_at_next_position_when_user_has_existing_alerts(self):
        """Third alert for a user with two existing gets position=3."""
        from core.db import create_user_alert

        with patch("core.db._fetchone") as mock_fetchone:
            mock_fetchone.side_effect = [{"max_pos": 2}, {"id": 99}]

            alert_id = create_user_alert(
                user_id=5,
                alert={
                    "topics": ["devops"],
                    "seniority": [],
                    "locations": [],
                    "sources": [],
                    "keywords": [],
                    "min_salary": None,
                },
            )

            assert alert_id == 99
            insert_call = mock_fetchone.call_args_list[1]
            params = insert_call[0][1]
            assert params[1] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_user_alerts.py::TestCreateUserAlert -v`
Expected: FAIL with `ImportError: cannot import name 'create_user_alert' from 'core.db'`

- [ ] **Step 3: Implement `create_user_alert`**

Add this section to `core/db.py` after `update_user_subscriptions` (around line 509). Place a section header above:

```python
# =============================================================================
# User Alerts (multi-alert subscriptions)
# =============================================================================

def create_user_alert(user_id: int, alert: dict) -> int:
    """
    Insert a new alert for the user at the next available 1-based position.
    `alert` keys: topics, seniority, locations, sources, keywords (all lists),
    min_salary (int|None). Returns the new alert id.
    New alerts default to dm_enabled=True.
    """
    max_row = _fetchone(
        "SELECT MAX(position) AS max_pos FROM user_alerts WHERE user_id = %s",
        (user_id,),
    )
    next_position = (max_row["max_pos"] or 0) + 1

    new_row = _fetchone(
        """
        INSERT INTO user_alerts
            (user_id, position, topics, seniority, locations, sources, keywords, min_salary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            user_id,
            next_position,
            alert.get("topics", []),
            alert.get("seniority", []),
            alert.get("locations", []),
            alert.get("sources", []),
            alert.get("keywords", []),
            alert.get("min_salary"),
        ),
    )
    return new_row["id"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_user_alerts.py::TestCreateUserAlert -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_user_alerts.py
git commit -m "feat(db): add create_user_alert with auto-incrementing position"
```

---

## Task 3: `core/db.py` — `get_user_alerts` and `get_user_alert`

**Files:**
- Modify: `core/db.py`
- Modify: `tests/test_user_alerts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_alerts.py`:

```python
# ---------------------------------------------------------------------------
# get_user_alerts / get_user_alert
# ---------------------------------------------------------------------------

class TestGetUserAlerts:
    def test_returns_list_ordered_by_position(self):
        from core.db import get_user_alerts
        rows = [
            {"id": 1, "user_id": 7, "position": 1, "topics": ["backend"]},
            {"id": 2, "user_id": 7, "position": 2, "topics": ["devops"]},
        ]
        with patch("core.db._fetchall", return_value=rows) as mock_all:
            result = get_user_alerts(user_id=7)
            assert result == rows
            sql = mock_all.call_args[0][0]
            assert "ORDER BY position" in sql

    def test_empty_when_user_has_no_alerts(self):
        from core.db import get_user_alerts
        with patch("core.db._fetchall", return_value=[]):
            assert get_user_alerts(user_id=99) == []


class TestGetUserAlert:
    def test_returns_single_alert(self):
        from core.db import get_user_alert
        with patch("core.db._fetchone", return_value={"id": 1, "position": 1}):
            assert get_user_alert(user_id=7, position=1) == {"id": 1, "position": 1}

    def test_returns_none_when_missing(self):
        from core.db import get_user_alert
        with patch("core.db._fetchone", return_value=None):
            assert get_user_alert(user_id=7, position=99) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_user_alerts.py::TestGetUserAlerts tests/test_user_alerts.py::TestGetUserAlert -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement both functions**

Append to the `User Alerts` section in `core/db.py`:

```python
def get_user_alerts(user_id: int) -> list[dict]:
    """Return all alerts for a user, ordered by position ascending."""
    return _fetchall(
        "SELECT * FROM user_alerts WHERE user_id = %s ORDER BY position ASC",
        (user_id,),
    )


def get_user_alert(user_id: int, position: int) -> Optional[dict]:
    """Return the alert at the given 1-based position, or None."""
    return _fetchone(
        "SELECT * FROM user_alerts WHERE user_id = %s AND position = %s",
        (user_id, position),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_user_alerts.py -v`
Expected: PASS (4 tests total)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_user_alerts.py
git commit -m "feat(db): add get_user_alerts and get_user_alert"
```

---

## Task 4: `core/db.py` — `update_user_alert`

**Files:**
- Modify: `core/db.py`
- Modify: `tests/test_user_alerts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_alerts.py`:

```python
# ---------------------------------------------------------------------------
# update_user_alert
# ---------------------------------------------------------------------------

class TestUpdateUserAlert:
    def test_updates_filter_fields(self):
        from core.db import update_user_alert
        with patch("core.db._execute", return_value={"id": 1}) as mock_exec:
            ok = update_user_alert(
                user_id=7,
                position=2,
                alert={
                    "topics": ["frontend"],
                    "seniority": ["mid"],
                    "locations": ["remote"],
                    "sources": ["linkedin"],
                    "keywords": ["react"],
                    "min_salary": 80000,
                },
            )
            assert ok is True
            sql = mock_exec.call_args[0][0]
            params = mock_exec.call_args[0][1]
            assert "UPDATE user_alerts" in sql
            assert "RETURNING id" in sql
            # Last two params are the WHERE clause: user_id, position
            assert params[-2] == 7
            assert params[-1] == 2

    def test_returns_false_when_no_row_matched(self):
        from core.db import update_user_alert
        with patch("core.db._execute", return_value=None):
            assert update_user_alert(user_id=7, position=99, alert={"topics": []}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_user_alerts.py::TestUpdateUserAlert -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `update_user_alert`**

Append to `core/db.py`:

```python
def update_user_alert(user_id: int, position: int, alert: dict) -> bool:
    """
    Replace the filter fields of an existing alert.
    Returns True if a row was matched and updated, False otherwise.
    """
    row = _execute(
        """
        UPDATE user_alerts
        SET topics = %s, seniority = %s, locations = %s, sources = %s,
            keywords = %s, min_salary = %s
        WHERE user_id = %s AND position = %s
        RETURNING id
        """,
        (
            alert.get("topics", []),
            alert.get("seniority", []),
            alert.get("locations", []),
            alert.get("sources", []),
            alert.get("keywords", []),
            alert.get("min_salary"),
            user_id,
            position,
        ),
    )
    return row is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_user_alerts.py -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_user_alerts.py
git commit -m "feat(db): add update_user_alert"
```

---

## Task 5: `core/db.py` — `set_alert_dm_enabled`

**Files:**
- Modify: `core/db.py`
- Modify: `tests/test_user_alerts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_alerts.py`:

```python
# ---------------------------------------------------------------------------
# set_alert_dm_enabled
# ---------------------------------------------------------------------------

class TestSetAlertDmEnabled:
    def test_returns_true_when_alert_exists(self):
        from core.db import set_alert_dm_enabled
        with patch("core.db._execute", return_value={"id": 5}) as mock_exec:
            ok = set_alert_dm_enabled(user_id=7, position=1, enabled=False)
            assert ok is True
            sql = mock_exec.call_args[0][0]
            params = mock_exec.call_args[0][1]
            assert "UPDATE user_alerts" in sql
            assert "dm_enabled" in sql
            assert params == (False, 7, 1)

    def test_returns_false_when_alert_missing(self):
        from core.db import set_alert_dm_enabled
        with patch("core.db._execute", return_value=None):
            assert set_alert_dm_enabled(user_id=7, position=99, enabled=True) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_user_alerts.py::TestSetAlertDmEnabled -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `set_alert_dm_enabled`**

Append to `core/db.py`:

```python
def set_alert_dm_enabled(user_id: int, position: int, enabled: bool) -> bool:
    """Toggle the per-alert DM flag. Returns True if a row was updated."""
    row = _execute(
        """
        UPDATE user_alerts SET dm_enabled = %s
        WHERE user_id = %s AND position = %s
        RETURNING id
        """,
        (enabled, user_id, position),
    )
    return row is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_user_alerts.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_user_alerts.py
git commit -m "feat(db): add set_alert_dm_enabled"
```

---

## Task 6: `core/db.py` — `delete_user_alert` with position re-pack

**Files:**
- Modify: `core/db.py`
- Modify: `tests/test_user_alerts.py`

This delete must run inside a single transaction so that after deleting alert at position N, all alerts with `position > N` for the same user have their `position` decremented by 1. This avoids gaps.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_alerts.py`:

```python
# ---------------------------------------------------------------------------
# delete_user_alert (with position re-pack)
# ---------------------------------------------------------------------------

class TestDeleteUserAlert:
    def test_deletes_and_repacks_higher_positions(self):
        """Deleting alert #2 of 3 must shift #3 → #2 in the same transaction."""
        from core.db import delete_user_alert

        # Mock the connection context-manager + cursor so we can observe the
        # ordered statements executed in one TX.
        executed = []

        class FakeCursor:
            def __init__(self):
                self.rowcount = 0
                self.description = None

            def execute(self, sql, params=()):
                executed.append((sql.strip().split()[0].upper(), params))
                # Pretend the DELETE matched one row
                if sql.strip().upper().startswith("DELETE"):
                    self.rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeConn:
            def cursor(self, cursor_factory=None):
                return FakeCursor()

            def commit(self): pass
            def rollback(self): pass

        from contextlib import contextmanager

        @contextmanager
        def fake_conn():
            yield FakeConn()

        with patch("core.db._get_conn", fake_conn):
            ok = delete_user_alert(user_id=7, position=2)

        assert ok is True
        # First op must be DELETE, second must be UPDATE (re-pack)
        assert executed[0][0] == "DELETE"
        assert executed[1][0] == "UPDATE"
        # The UPDATE must scope to the same user and positions > 2
        assert executed[1][1] == (7, 2)

    def test_returns_false_when_alert_missing(self):
        from core.db import delete_user_alert

        class FakeCursor:
            def __init__(self):
                self.rowcount = 0
                self.description = None
            def execute(self, sql, params=()):
                pass
            def __enter__(self): return self
            def __exit__(self, *args): return False

        class FakeConn:
            def cursor(self, cursor_factory=None):
                return FakeCursor()
            def commit(self): pass
            def rollback(self): pass

        from contextlib import contextmanager

        @contextmanager
        def fake_conn():
            yield FakeConn()

        with patch("core.db._get_conn", fake_conn):
            assert delete_user_alert(user_id=7, position=99) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_user_alerts.py::TestDeleteUserAlert -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `delete_user_alert`**

Append to `core/db.py`:

```python
def delete_user_alert(user_id: int, position: int) -> bool:
    """
    Delete one alert and re-pack any higher positions in the same transaction
    so positions stay contiguous. Returns True if a row was deleted.
    """
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "DELETE FROM user_alerts WHERE user_id = %s AND position = %s",
                (user_id, position),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                """
                UPDATE user_alerts
                SET position = position - 1
                WHERE user_id = %s AND position > %s
                """,
                (user_id, position),
            )
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_user_alerts.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_user_alerts.py
git commit -m "feat(db): add delete_user_alert with atomic position re-pack"
```

---

## Task 7: `core/db.py` — `delete_all_user_alerts` + remove legacy `update_user_subscriptions`

**Files:**
- Modify: `core/db.py`
- Modify: `tests/test_user_alerts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_alerts.py`:

```python
# ---------------------------------------------------------------------------
# delete_all_user_alerts
# ---------------------------------------------------------------------------

class TestDeleteAllUserAlerts:
    def test_returns_count_of_deleted_rows(self):
        from core.db import delete_all_user_alerts
        with patch("core.db._fetchone", return_value={"count": 3}) as mock_fone:
            count = delete_all_user_alerts(user_id=7)
            assert count == 3
            sql = mock_fone.call_args[0][0]
            assert "DELETE FROM user_alerts" in sql
            assert "WHERE user_id = %s" in sql
            assert "RETURNING" in sql

    def test_returns_zero_when_user_has_no_alerts(self):
        from core.db import delete_all_user_alerts
        with patch("core.db._fetchone", return_value=None):
            assert delete_all_user_alerts(user_id=99) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_user_alerts.py::TestDeleteAllUserAlerts -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `delete_all_user_alerts` and remove `update_user_subscriptions`**

Append to `core/db.py`:

```python
def delete_all_user_alerts(user_id: int) -> int:
    """Delete every alert for a user. Returns the count of deleted rows."""
    row = _fetchone(
        """
        WITH deleted AS (
            DELETE FROM user_alerts WHERE user_id = %s RETURNING id
        )
        SELECT COUNT(*) AS count FROM deleted
        """,
        (user_id,),
    )
    return row["count"] if row else 0
```

Then remove the now-unused legacy function. In `core/db.py`, delete lines 503-508 (the `update_user_subscriptions` function). Also remove the section comment block above it if it now only contains `get_or_create_user`. Keep the `Users` section header — `get_or_create_user` stays.

The exact lines to delete (verify via Read before editing):

```python
def update_user_subscriptions(telegram_id: int, subscriptions: dict) -> None:
    """Persist a user's subscription preferences."""
    _execute(
        "UPDATE users SET subscriptions = %s WHERE telegram_id = %s",
        (json.dumps(subscriptions), telegram_id),
    )
```

- [ ] **Step 4: Run all db tests to verify they pass and nothing else broke**

Run: `pytest tests/test_user_alerts.py tests/test_db.py -v`
Expected: PASS (existing test_db.py tests + 12 user_alerts tests)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_user_alerts.py
git commit -m "feat(db): add delete_all_user_alerts; remove legacy update_user_subscriptions"
```

---

## Task 8: Update `_handle_sub_source_done` to write to `user_alerts`

**Files:**
- Modify: `bot/callbacks.py:270-296`

The existing handler builds a payload and calls `db.update_user_subscriptions(user.id, subscriptions)`. We replace that with a write to `user_alerts`. The same handler is reused for both create and edit — Edit sets `context.user_data["edit_position"] = N` to switch behavior.

- [ ] **Step 1: Replace `_handle_sub_source_done`**

Open `bot/callbacks.py`. Find the function `_handle_sub_source_done` (currently ~lines 270-296) and replace its body with:

```python
async def _handle_sub_source_done(query, user, context) -> None:
    """Source selection done — save the alert (create or edit)."""
    topics = list(context.user_data.get("sub_topics", set()))
    seniority = list(context.user_data.get("sub_seniority", set()))
    locations = list(context.user_data.get("sub_locations", set()))
    sources = list(context.user_data.get("sub_sources", set()))

    alert_payload = {
        "topics": topics,
        "seniority": seniority,
        "locations": locations,
        "sources": sources,
        "keywords": list(context.user_data.get("sub_keywords", [])),
        "min_salary": context.user_data.get("sub_min_salary"),
    }

    db_user = db.get_or_create_user(user.id, user.username or "")
    edit_position = context.user_data.pop("edit_position", None)

    if edit_position is not None:
        ok = db.update_user_alert(db_user["id"], edit_position, alert_payload)
        if ok:
            header = f"✅ Alert #{edit_position} updated."
        else:
            header = f"⚠️ Alert #{edit_position} no longer exists."
    else:
        new_id = db.create_user_alert(db_user["id"], alert_payload)
        # Look up its position to show in the confirmation
        alerts = db.get_user_alerts(db_user["id"])
        position = next((a["position"] for a in alerts if a["id"] == new_id), len(alerts))
        header = f"✅ Alert #{position} created. You'll receive DM alerts for matching jobs."

    summary = _format_sub_summary(topics, seniority, locations, sources)
    await query.edit_message_text(f"{header}\n\n{summary}")

    # Clean up temp data
    context.user_data.pop("sub_topics", None)
    context.user_data.pop("sub_seniority", None)
    context.user_data.pop("sub_locations", None)
    context.user_data.pop("sub_sources", None)
    context.user_data.pop("sub_keywords", None)
    context.user_data.pop("sub_min_salary", None)
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.callbacks"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/callbacks.py
git commit -m "feat(bot): _handle_sub_source_done writes to user_alerts (create or edit)"
```

---

## Task 9: Notification matching — rename to `_job_matches_alert` and update callers

**Files:**
- Modify: `bot/notifications.py:21-76`
- Modify: `tests/test_notifications.py`

The function body doesn't change — only the name and the docstring. The new name reflects that it matches against a single alert dict.

- [ ] **Step 1: Update tests first to use the new name**

In `tests/test_notifications.py`, do a find/replace from `_job_matches_subscription` to `_job_matches_alert` throughout the file. The fixtures already produce dicts with the same shape (`topics`, `seniority`, etc.), so they need no change.

The import line at the top changes from:
```python
from bot.notifications import _job_matches_subscription, _job_blocked_by_blacklist
```
to:
```python
from bot.notifications import _job_matches_alert, _job_blocked_by_blacklist
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notifications.py -v`
Expected: FAIL with `ImportError: cannot import name '_job_matches_alert'`

- [ ] **Step 3: Rename in `bot/notifications.py`**

In `bot/notifications.py`, rename the function and update its docstring:

```python
def _job_matches_alert(job: Job, alert: dict) -> bool:
    """Check if a job matches a single user alert (filter dict)."""
    if not alert:
        return False

    # Check topics
    sub_topics = set(alert.get("topics", []))
    if sub_topics and not sub_topics.intersection(set(job.topics)):
        return False

    # Check seniority
    sub_seniority = alert.get("seniority", [])
    if sub_seniority and job.seniority not in sub_seniority:
        return False

    # Check sources — match against source key and original_source (for aggregators like JSearch)
    sub_sources = set(alert.get("sources", []))
    if sub_sources:
        _DISPLAY_TO_KEY = {
            "LinkedIn": "linkedin", "Indeed": "indeed",
            "Glassdoor": "glassdoor", "ZipRecruiter": "ziprecruiter",
            "Monster": "monster",
        }
        job_source_key = job.source
        original_key = _DISPLAY_TO_KEY.get(job.original_source, "")
        if job_source_key not in sub_sources and original_key not in sub_sources:
            return False

    # Check locations — "remote" matches is_remote, others match country code
    sub_locations = alert.get("locations", [])
    if sub_locations:
        matched = False
        for loc in sub_locations:
            if loc == "remote" and job.is_remote:
                matched = True
                break
            if loc == job.country:
                matched = True
                break
        if not matched:
            return False

    # Check keywords
    sub_keywords = alert.get("keywords", [])
    if sub_keywords:
        title_lower = job.title.lower()
        if not any(kw.lower() in title_lower for kw in sub_keywords):
            return False

    # Check min salary
    min_salary = alert.get("min_salary")
    if min_salary and job.salary_max and job.salary_max < min_salary:
        return False

    return True
```

`notify_subscribers` still calls the old name; we'll fix it in Task 10. So tests will pass but the bot would fail at runtime — that's fine because Task 10 follows immediately.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notifications.py -v`
Expected: PASS (all renamed tests)

- [ ] **Step 5: Commit**

```bash
git add bot/notifications.py tests/test_notifications.py
git commit -m "refactor(notifications): rename _job_matches_subscription -> _job_matches_alert"
```

---

## Task 10: Rewrite `notify_subscribers` for per-alert matching

**Files:**
- Modify: `bot/notifications.py:97-165`
- Modify: `tests/test_notifications.py` (add multi-alert scenarios)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notifications.py` (at the bottom, before the last newline):

```python
# ---------------------------------------------------------------------------
# notify_subscribers — per-alert matching, first-match wins
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


class _FakeBot:
    def __init__(self):
        self.send_message = AsyncMock()


class TestNotifySubscribersPerAlert:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _user(self, uid=1, telegram_id=42):
        return {"id": uid, "telegram_id": telegram_id, "notify_dm": True}

    def test_first_match_wins_one_dm_per_job(self):
        """User has two alerts that both match the job → exactly one DM sent."""
        from bot.notifications import notify_subscribers

        job = _make_job(topics=["backend"], country="EG")
        bot = _FakeBot()

        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True},
            {"position": 2, "topics": ["backend"], "seniority": [], "locations": ["EG"],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True},
        ]

        with patch("core.db._fetchall", return_value=[self._user()]), \
             patch("core.db.get_user_alerts", return_value=alerts), \
             patch("core.db.get_blacklist", return_value={"companies": [], "keywords": []}):
            sent = self._run(notify_subscribers(bot, [(job, 99)]))

        assert sent == 1
        assert bot.send_message.call_count == 1

    def test_dm_disabled_alert_is_skipped(self):
        """An alert with dm_enabled=False does not produce a DM even if it matches."""
        from bot.notifications import notify_subscribers

        job = _make_job(topics=["backend"])
        bot = _FakeBot()

        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": False},
        ]

        with patch("core.db._fetchall", return_value=[self._user()]), \
             patch("core.db.get_user_alerts", return_value=alerts), \
             patch("core.db.get_blacklist", return_value={"companies": [], "keywords": []}):
            sent = self._run(notify_subscribers(bot, [(job, 99)]))

        assert sent == 0
        assert bot.send_message.call_count == 0

    def test_global_notify_dm_false_skips_user(self):
        """User-level notify_dm=False suppresses all alerts for that user."""
        from bot.notifications import notify_subscribers

        job = _make_job(topics=["backend"])
        bot = _FakeBot()

        users = [{"id": 1, "telegram_id": 42, "notify_dm": False}]
        # _fetchall is the SELECT users WHERE notify_dm = TRUE — should return empty
        with patch("core.db._fetchall", return_value=[]):
            sent = self._run(notify_subscribers(bot, [(job, 99)]))

        assert sent == 0
        assert bot.send_message.call_count == 0

    def test_no_alerts_means_no_dm(self):
        from bot.notifications import notify_subscribers
        job = _make_job(topics=["backend"])
        bot = _FakeBot()

        with patch("core.db._fetchall", return_value=[self._user()]), \
             patch("core.db.get_user_alerts", return_value=[]), \
             patch("core.db.get_blacklist", return_value={"companies": [], "keywords": []}):
            sent = self._run(notify_subscribers(bot, [(job, 99)]))

        assert sent == 0
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/test_notifications.py::TestNotifySubscribersPerAlert -v`
Expected: FAIL — current `notify_subscribers` reads `subscriptions` column and calls the old function name.

- [ ] **Step 3: Replace `notify_subscribers` body**

In `bot/notifications.py`, replace the entire `notify_subscribers` function (currently ~lines 97-165) with:

```python
async def notify_subscribers(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send DM alerts to subscribed users for matching jobs.

    Per-user behavior:
      - Skips users with notify_dm = FALSE (global kill switch).
      - Iterates the user's alerts in position order; first matching alert
        with dm_enabled=True wins (one DM per (user, job) pair).
      - Applies the user-level blacklist after a match.
      - Rate limits at MAX_DMS_PER_USER_PER_HOUR DMs per user.

    Args:
        bot: Telegram Bot instance
        jobs: List of (Job, db_id) tuples

    Returns: Total DMs sent
    """
    try:
        users = db._fetchall(
            "SELECT * FROM users WHERE notify_dm = TRUE"
        )
    except Exception as e:
        log.error(f"Failed to fetch subscribers: {e}")
        return 0

    total_sent = 0

    for user_row in users:
        telegram_id = user_row["telegram_id"]
        user_id = user_row["id"]
        alerts = db.get_user_alerts(user_id)
        if not alerts:
            continue
        blacklist = db.get_blacklist(user_id)
        dm_count = 0

        for job, db_id in jobs:
            if dm_count >= MAX_DMS_PER_USER_PER_HOUR:
                log.info(f"Rate limit hit for user {telegram_id}")
                break

            matched = None
            for alert in alerts:
                if not alert.get("dm_enabled", True):
                    continue
                if _job_matches_alert(job, alert):
                    matched = alert
                    break  # first-match wins

            if matched is None:
                continue
            if _job_blocked_by_blacklist(job, blacklist):
                continue

            try:
                msg = format_job_message(job)
                await bot.send_message(
                    chat_id=telegram_id,
                    text=f"🔔 New matching job (Alert #{matched['position']}):\n\n{msg}",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=job_buttons(db_id),
                )
                dm_count += 1
                total_sent += 1
            except TelegramError as e:
                err = str(e).lower()
                if any(phrase in err for phrase in (
                    "bot was blocked", "user not found",
                    "chat not found", "forbidden",
                    "bot can't initiate conversation",
                    "have no rights to send a message",
                )):
                    db._execute(
                        "UPDATE users SET notify_dm = FALSE WHERE telegram_id = %s",
                        (telegram_id,),
                    )
                    log.info(f"Disabled DMs for user {telegram_id}: {e}")
                    break
                else:
                    log.warning(f"DM failed for {telegram_id}: {e}")

    log.info(f"📬 Sent {total_sent} DM alerts across {len(users)} subscribers")
    return total_sent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notifications.py -v`
Expected: PASS (all original tests + 4 new multi-alert tests)

- [ ] **Step 5: Commit**

```bash
git add bot/notifications.py tests/test_notifications.py
git commit -m "feat(notifications): per-alert matching loop with first-match wins"
```

---

## Task 11: New keyboard builders

**Files:**
- Modify: `bot/keyboards.py`

Three new builders, used by Tasks 12 and 13.

- [ ] **Step 1: Append the builders to `bot/keyboards.py`**

Append at the end of the file (after `pagination_keyboard`):

```python
def alerts_unsub_keyboard(alerts: list[dict]) -> InlineKeyboardMarkup:
    """Chooser shown by /unsubscribe — one row per alert plus All / Cancel."""
    buttons = []
    for a in alerts:
        position = a["position"]
        label = _alert_short_label(a)
        buttons.append([InlineKeyboardButton(
            f"Alert #{position} — {label}",
            callback_data=f"unsub:{position}",
        )])
    buttons.append([InlineKeyboardButton(
        "— Remove all alerts —",
        callback_data="unsub:all",
    )])
    buttons.append([InlineKeyboardButton(
        "Cancel",
        callback_data="unsub:cancel",
    )])
    return InlineKeyboardMarkup(buttons)


def alert_card_keyboard(position: int, dm_enabled: bool) -> InlineKeyboardMarkup:
    """Per-alert action row in /mysubs: Edit / Delete / DM toggle."""
    dm_label = "🔔 DM On" if dm_enabled else "🔕 DM Off"
    dm_target = "off" if dm_enabled else "on"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✏ Edit #{position}", callback_data=f"edit:{position}"),
        InlineKeyboardButton(f"🗑 Delete #{position}", callback_data=f"del:{position}"),
        InlineKeyboardButton(dm_label, callback_data=f"dm:{position}:{dm_target}"),
    ]])


def confirm_remove_all_keyboard() -> InlineKeyboardMarkup:
    """Confirmation prompt shown before bulk-deleting all alerts."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, delete all", callback_data="unsub:all_confirm"),
        InlineKeyboardButton("Cancel", callback_data="unsub:cancel"),
    ]])


def _alert_short_label(alert: dict) -> str:
    """Compose a short human-readable label for an alert (used in chooser rows)."""
    parts = []
    topics = alert.get("topics") or []
    if topics:
        parts.append(", ".join(topics[:3]) + ("…" if len(topics) > 3 else ""))
    seniority = alert.get("seniority") or []
    if seniority:
        parts.append("/".join(seniority))
    locations = alert.get("locations") or []
    if locations:
        parts.append("/".join(locations[:3]))
    return " · ".join(parts) if parts else "all jobs"
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "from bot.keyboards import alerts_unsub_keyboard, alert_card_keyboard, confirm_remove_all_keyboard; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add bot/keyboards.py
git commit -m "feat(bot): add keyboard builders for alert chooser, card row, and confirm"
```

---

## Task 12: Rewrite `cmd_mysubs` with per-alert cards

**Files:**
- Modify: `bot/commands.py:100-127`

- [ ] **Step 1: Replace `cmd_mysubs`**

Open `bot/commands.py`. Replace `cmd_mysubs` (currently ~lines 100-127) with:

```python
async def cmd_mysubs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    alerts = db.get_user_alerts(db_user["id"])

    if not alerts:
        await update.message.reply_text(
            "No active alerts. Use /subscribe to create one."
        )
        return

    from bot.keyboards import (
        alert_card_keyboard, LOCATION_OPTIONS, SOURCE_OPTIONS,
    )
    location_labels = dict(LOCATION_OPTIONS)
    source_labels = dict(SOURCE_OPTIONS)

    await update.message.reply_text(
        f"📋 <b>Your alerts ({len(alerts)}):</b>",
        parse_mode="HTML",
    )

    for a in alerts:
        position = a["position"]
        lines = [f"<b>#{position}</b>"]
        if a.get("topics"):
            lines.append(f"Topics: {', '.join(a['topics'])}")
        if a.get("seniority"):
            lines.append(f"Seniority: {', '.join(a['seniority'])}")
        if a.get("locations"):
            lines.append(
                f"Locations: {', '.join(location_labels.get(l, l) for l in a['locations'])}"
            )
        else:
            lines.append("Locations: All (no filter)")
        if a.get("sources"):
            lines.append(
                f"Sources: {', '.join(source_labels.get(s, s) for s in a['sources'])}"
            )
        else:
            lines.append("Sources: All (no filter)")
        if a.get("keywords"):
            lines.append(f"Keywords: {', '.join(a['keywords'])}")
        if a.get("min_salary"):
            lines.append(f"Min salary: ${a['min_salary']:,}/year")
        lines.append("DM: " + ("🔔 on" if a.get("dm_enabled", True) else "🔕 off"))

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=alert_card_keyboard(position, a.get("dm_enabled", True)),
        )
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.commands"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/commands.py
git commit -m "feat(bot): /mysubs renders one card per alert with action buttons"
```

---

## Task 13: Rewrite `cmd_unsubscribe` with chooser

**Files:**
- Modify: `bot/commands.py:93-97`

- [ ] **Step 1: Replace `cmd_unsubscribe`**

Open `bot/commands.py`. Replace `cmd_unsubscribe` (currently ~lines 93-97) with:

```python
async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a chooser of alerts to remove (or 'remove all')."""
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    alerts = db.get_user_alerts(db_user["id"])

    if not alerts:
        await update.message.reply_text(
            "You have no active alerts. Use /subscribe to create one."
        )
        return

    from bot.keyboards import alerts_unsub_keyboard
    await update.message.reply_text(
        "Which alert do you want to remove?",
        reply_markup=alerts_unsub_keyboard(alerts),
    )
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.commands"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/commands.py
git commit -m "feat(bot): /unsubscribe shows alert chooser with bulk-delete option"
```

---

## Task 14: Add `unsub:*` callback handlers

**Files:**
- Modify: `bot/callbacks.py`

Adds the chooser-side handlers used by `cmd_unsubscribe`. Three callback values:
- `unsub:<n>` — delete one alert immediately, edit message in place.
- `unsub:all` — show confirmation prompt.
- `unsub:all_confirm` — actually delete all.
- `unsub:cancel` — dismiss without changes.

- [ ] **Step 1: Add the new callback to `handle_callback`'s router**

Open `bot/callbacks.py`. Find the `handle_callback` function (~lines 19-61). Add new routes before the `else: log.warning(...)` line:

```python
    elif data.startswith("unsub:"):
        await _handle_unsub(query, user, context, data)
    elif data.startswith("del:"):
        await _handle_del(query, user, context, data)
    elif data.startswith("dm:"):
        await _handle_dm(query, user, context, data)
    elif data.startswith("edit:"):
        await _handle_edit(query, user, context, data)
```

- [ ] **Step 2: Add the `_handle_unsub` implementation**

Append at the end of `bot/callbacks.py`:

```python
async def _handle_unsub(query, user, context, data: str) -> None:
    """Handle /unsubscribe chooser callbacks: unsub:<n>, unsub:all, unsub:all_confirm, unsub:cancel."""
    action = data.split(":", 1)[1]
    db_user = db.get_or_create_user(user.id, user.username or "")

    if action == "cancel":
        await query.edit_message_text("Cancelled.")
        return

    if action == "all":
        from bot.keyboards import confirm_remove_all_keyboard
        alerts = db.get_user_alerts(db_user["id"])
        await query.edit_message_text(
            f"⚠️ Remove ALL {len(alerts)} alerts? This cannot be undone.",
            reply_markup=confirm_remove_all_keyboard(),
        )
        return

    if action == "all_confirm":
        count = db.delete_all_user_alerts(db_user["id"])
        await query.edit_message_text(f"✅ Removed {count} alert(s).")
        return

    # unsub:<n>
    try:
        position = int(action)
    except ValueError:
        log.warning(f"Bad unsub callback: {data}")
        return

    ok = db.delete_user_alert(db_user["id"], position)
    if not ok:
        await query.edit_message_text(f"⚠️ Alert #{position} no longer exists.")
        return
    remaining = len(db.get_user_alerts(db_user["id"]))
    await query.edit_message_text(
        f"✅ Alert #{position} removed. You have {remaining} alert(s) left."
    )
```

- [ ] **Step 3: Smoke-check syntax**

Run: `python -c "import bot.callbacks"`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add bot/callbacks.py
git commit -m "feat(bot): unsub:* callbacks for per-alert and bulk delete with confirm"
```

---

## Task 15: Add `del:*` callback (delete from `/mysubs` card)

**Files:**
- Modify: `bot/callbacks.py`

The `del:<n>` callback fires from the per-alert card in `/mysubs`. Behavior: delete the alert, edit the card message in place to show a strikethrough confirmation.

- [ ] **Step 1: Add `_handle_del` to `bot/callbacks.py`**

Append at the end of `bot/callbacks.py`:

```python
async def _handle_del(query, user, context, data: str) -> None:
    """Delete a single alert from a /mysubs card. Edits the card in place."""
    try:
        position = int(data.split(":", 1)[1])
    except ValueError:
        log.warning(f"Bad del callback: {data}")
        return

    db_user = db.get_or_create_user(user.id, user.username or "")
    ok = db.delete_user_alert(db_user["id"], position)
    if not ok:
        await query.edit_message_text(f"⚠️ Alert #{position} no longer exists.")
        return
    await query.edit_message_text(f"🗑 Alert #{position} removed.")
```

Note: positions of *other* alert cards still on screen will now be wrong (because the re-pack shifted them down). Users running `/mysubs` again refreshes the list. Documenting this trade-off as a known UX detail rather than silently re-rendering every other card on screen — Telegram's API doesn't let one callback edit unrelated messages. The chooser flow (`/unsubscribe`) is unaffected since it only shows one chooser message.

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.callbacks"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/callbacks.py
git commit -m "feat(bot): del:* callback to delete a single alert from /mysubs card"
```

---

## Task 16: Add `dm:*` callback (in-place toggle)

**Files:**
- Modify: `bot/callbacks.py`

`dm:<n>:<on|off>` toggles the DM flag for one alert and edits the card in place to flip the button label.

- [ ] **Step 1: Add `_handle_dm`**

Append at the end of `bot/callbacks.py`:

```python
async def _handle_dm(query, user, context, data: str) -> None:
    """Toggle DM flag for one alert; re-render the card in place."""
    parts = data.split(":")
    if len(parts) != 3:
        log.warning(f"Bad dm callback: {data}")
        return
    try:
        position = int(parts[1])
    except ValueError:
        log.warning(f"Bad dm callback position: {data}")
        return
    target = parts[2]
    if target not in ("on", "off"):
        log.warning(f"Bad dm callback target: {data}")
        return
    enabled = target == "on"

    db_user = db.get_or_create_user(user.id, user.username or "")
    ok = db.set_alert_dm_enabled(db_user["id"], position, enabled)
    if not ok:
        await query.edit_message_text(f"⚠️ Alert #{position} no longer exists.")
        return

    # Re-render the card with the new label.
    alert = db.get_user_alert(db_user["id"], position)
    if alert is None:
        await query.edit_message_text(f"⚠️ Alert #{position} no longer exists.")
        return

    from bot.keyboards import (
        alert_card_keyboard, LOCATION_OPTIONS, SOURCE_OPTIONS,
    )
    location_labels = dict(LOCATION_OPTIONS)
    source_labels = dict(SOURCE_OPTIONS)

    lines = [f"<b>#{position}</b>"]
    if alert.get("topics"):
        lines.append(f"Topics: {', '.join(alert['topics'])}")
    if alert.get("seniority"):
        lines.append(f"Seniority: {', '.join(alert['seniority'])}")
    if alert.get("locations"):
        lines.append(
            f"Locations: {', '.join(location_labels.get(l, l) for l in alert['locations'])}"
        )
    else:
        lines.append("Locations: All (no filter)")
    if alert.get("sources"):
        lines.append(
            f"Sources: {', '.join(source_labels.get(s, s) for s in alert['sources'])}"
        )
    else:
        lines.append("Sources: All (no filter)")
    if alert.get("keywords"):
        lines.append(f"Keywords: {', '.join(alert['keywords'])}")
    if alert.get("min_salary"):
        lines.append(f"Min salary: ${alert['min_salary']:,}/year")
    lines.append("DM: " + ("🔔 on" if enabled else "🔕 off"))

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=alert_card_keyboard(position, enabled),
    )
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.callbacks"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/callbacks.py
git commit -m "feat(bot): dm:* callback toggles per-alert DM flag in place"
```

---

## Task 17: Add `edit:*` callback (re-enter wizard with state)

**Files:**
- Modify: `bot/callbacks.py`

Tapping Edit pre-seeds the wizard state with the alert's current filters and starts the user back at Step 1 (topics). When they reach Step 4 done, `_handle_sub_source_done` (Task 8) checks for `edit_position` and calls `update_user_alert` instead of `create_user_alert`.

- [ ] **Step 1: Add `_handle_edit`**

Append at the end of `bot/callbacks.py`:

```python
async def _handle_edit(query, user, context, data: str) -> None:
    """Edit an existing alert: pre-seed wizard state, start at topics step."""
    try:
        position = int(data.split(":", 1)[1])
    except ValueError:
        log.warning(f"Bad edit callback: {data}")
        return

    db_user = db.get_or_create_user(user.id, user.username or "")
    alert = db.get_user_alert(db_user["id"], position)
    if alert is None:
        await query.edit_message_text(f"⚠️ Alert #{position} no longer exists.")
        return

    # Pre-seed wizard state
    context.user_data["sub_topics"] = set(alert.get("topics") or [])
    context.user_data["sub_seniority"] = set(alert.get("seniority") or [])
    context.user_data["sub_locations"] = set(alert.get("locations") or [])
    context.user_data["sub_sources"] = set(alert.get("sources") or [])
    context.user_data["sub_keywords"] = list(alert.get("keywords") or [])
    context.user_data["sub_min_salary"] = alert.get("min_salary")
    context.user_data["edit_position"] = position

    from bot.keyboards import topic_selection_keyboard
    await query.edit_message_text(
        f"Editing Alert #{position}\n\n"
        "Step 1/4: Adjust topics (tap to toggle, then press Done):",
        reply_markup=topic_selection_keyboard(context.user_data["sub_topics"]),
    )
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.callbacks"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/callbacks.py
git commit -m "feat(bot): edit:* callback re-enters wizard with pre-seeded state"
```

---

## Task 18: Update `HELP_TEXT` and `/start` welcome string

**Files:**
- Modify: `bot/commands.py:21-38`

Help text currently says `/unsubscribe — Remove all subscriptions` which is no longer accurate.

- [ ] **Step 1: Update HELP_TEXT**

In `bot/commands.py`, replace the two relevant lines in `HELP_TEXT`:

Find:
```
/subscribe — Set up personalized job alerts
/unsubscribe — Remove all subscriptions
/mysubs — View your current filters
```

Replace with:
```
/subscribe — Add a job alert (you can have multiple)
/unsubscribe — Remove an alert (or all of them)
/mysubs — View, edit, or toggle DMs for your alerts
```

- [ ] **Step 2: Smoke-check syntax**

Run: `python -c "import bot.commands"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add bot/commands.py
git commit -m "docs(bot): update /help text for multi-alert commands"
```

---

## Task 19: Migration integration test (opt-in)

**Files:**
- Create: `tests/test_migration_005.py`

The existing test suite is mock-only (no real DB connection). This test validates the SQL data migration in `005_user_alerts.sql` against a real Postgres, but skips itself when `TEST_DATABASE_URL` is not set so the default `pytest` run is unaffected.

- [ ] **Step 1: Create the test file**

```python
"""
Integration test for migration 005_user_alerts.sql.

Skipped unless TEST_DATABASE_URL points at a disposable Postgres database.
Example:
    TEST_DATABASE_URL=postgres://postgres@localhost:5432/migrations_test \
        pytest tests/test_migration_005.py -v

The test creates a clean schema, applies migrations 001..005, seeds two
users (one with subscriptions, one with empty), and asserts the resulting
user_alerts rows.
"""
import os
import pathlib
import json

import pytest

pytest.importorskip("psycopg2")
import psycopg2
from psycopg2.extras import RealDictCursor


TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL not set"
)


MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "supabase" / "migrations"
MIGRATIONS_TO_APPLY = [
    "001_init.sql",
    "002_applications_and_blacklist.sql",
    "003_add_posted_at.sql",
    "004_support_messages.sql",
    "005_user_alerts.sql",
]


@pytest.fixture
def fresh_db():
    """Drop and recreate the public schema, then apply migrations 001..005."""
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    yield conn
    conn.close()


def _apply_migrations_through_004(conn):
    """Apply 001..004 only — leaves users.subscriptions populated for the test."""
    with conn.cursor() as cur:
        for name in MIGRATIONS_TO_APPLY[:-1]:
            sql = (MIGRATIONS_DIR / name).read_text()
            cur.execute(sql)


def _apply_migration_005(conn):
    with conn.cursor() as cur:
        sql = (MIGRATIONS_DIR / "005_user_alerts.sql").read_text()
        cur.execute(sql)


def test_user_with_subscription_gets_one_alert(fresh_db):
    conn = fresh_db
    _apply_migrations_through_004(conn)

    sub = {
        "topics": ["backend", "devops"],
        "seniority": ["senior"],
        "locations": ["remote", "EG"],
        "sources": ["linkedin"],
        "keywords": ["python"],
        "min_salary": 80000,
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (telegram_id, username, subscriptions) VALUES (%s, %s, %s) RETURNING id",
            (12345, "alice", json.dumps(sub)),
        )
        user_id = cur.fetchone()[0]

    _apply_migration_005(conn)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_alerts WHERE user_id = %s ORDER BY position", (user_id,))
        rows = cur.fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["position"] == 1
    assert sorted(row["topics"]) == ["backend", "devops"]
    assert row["seniority"] == ["senior"]
    assert sorted(row["locations"]) == ["EG", "remote"]
    assert row["sources"] == ["linkedin"]
    assert row["keywords"] == ["python"]
    assert row["min_salary"] == 80000
    assert row["dm_enabled"] is True


def test_user_with_empty_subscriptions_produces_no_alert(fresh_db):
    conn = fresh_db
    _apply_migrations_through_004(conn)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (telegram_id, username, subscriptions) VALUES (%s, %s, %s) RETURNING id",
            (54321, "bob", json.dumps({})),
        )
        user_id = cur.fetchone()[0]

    _apply_migration_005(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_alerts WHERE user_id = %s", (user_id,))
        count = cur.fetchone()[0]

    assert count == 0
```

- [ ] **Step 2: Verify the test skips by default**

Run: `pytest tests/test_migration_005.py -v`
Expected: 2 tests SKIPPED (because `TEST_DATABASE_URL` is unset).

- [ ] **Step 3: (Optional) Run against a local Postgres to verify the migration logic**

If a disposable Postgres is available:
```bash
TEST_DATABASE_URL=postgres://postgres@localhost:5432/migrations_test pytest tests/test_migration_005.py -v
```
Expected: PASS (2 tests).

This step is optional for the commit; running the test in CI / staging is sufficient. The default `pytest` invocation must continue to skip cleanly.

- [ ] **Step 4: Commit**

```bash
git add tests/test_migration_005.py
git commit -m "test(migration): integration test for 005_user_alerts (opt-in, requires DB)"
```

---

## Task 20: Final test sweep

**Files:**
- (read-only) all modified files

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS for every existing test plus all newly added tests under `test_user_alerts.py` and `test_notifications.py`.

- [ ] **Step 2: Confirm no calls remain to `update_user_subscriptions`**

Run: `grep -rn "update_user_subscriptions" --include="*.py" .`
Expected: no results (or only in committed git history).

- [ ] **Step 3: Confirm no calls remain to `_job_matches_subscription`**

Run: `grep -rn "_job_matches_subscription" --include="*.py" .`
Expected: no results.

- [ ] **Step 4: If anything fails, fix and recommit (a separate commit per fix)**

Use the standard test → fix → run-again → commit cycle. Do not amend earlier commits.

---

## Out of scope (follow-up PRs)

- `supabase/migrations/006_drop_users_subscriptions.sql` — drop the legacy column after one safe deploy cycle.
- Per-alert rate limiting (currently the 20/hour cap is per user across all alerts).
- Optional alert names (current spec is numbered-only).
- Soft cap on alerts per user (current spec is unlimited).
