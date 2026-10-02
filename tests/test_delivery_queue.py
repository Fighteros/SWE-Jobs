"""
Tests for core/delivery_queue.py.

Unit tests mock core.db helpers. Integration tests live in
tests/test_delivery_queue_integration.py and require a disposable Postgres
 database via TEST_DATABASE_URL.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from core.models import Job
from core.delivery_queue import (
    DELIVERY_TYPE_GROUP_TOPIC,
    DELIVERY_TYPE_SUBSCRIBER_DM,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_SENT,
    STATUS_DEAD_LETTER,
    STATUS_SKIPPED,
    build_group_topic_deliveries,
    build_subscriber_dm_deliveries,
    enqueue_job_deliveries,
    claim_pending_deliveries,
    mark_delivery_sent,
    mark_delivery_failed,
    mark_delivery_skipped,
    release_delivery_to_pending,
    recover_stale_deliveries,
    replay_dead_letter,
    get_delivery_stats,
    _next_attempt_at,
)


@pytest.fixture
def sample_job():
    return Job(
        title="Senior Python Developer",
        company="Acme Corp",
        location="Cairo, Egypt",
        url="https://example.com/jobs/123",
        source="remotive",
        topics=["backend", "egypt"],
    )


@pytest.fixture
def sample_job_no_topics():
    return Job(
        title="Senior Python Developer",
        company="Acme Corp",
        location="Cairo, Egypt",
        url="https://example.com/jobs/124",
        source="remotive",
        topics=[],
    )


# ---------------------------------------------------------------------------
# Build group-topic delivery records
# ---------------------------------------------------------------------------

class TestBuildGroupTopicDeliveries:
    def test_one_record_per_topic(self, sample_job):
        rows = build_group_topic_deliveries([(sample_job, 1)])
        assert len(rows) == 2
        assert {r["recipient_key"] for r in rows} == {"backend", "egypt"}
        assert all(r["delivery_type"] == DELIVERY_TYPE_GROUP_TOPIC for r in rows)
        assert all(r["status"] == STATUS_PENDING for r in rows)

    def test_no_topics_creates_skipped_record(self, sample_job_no_topics):
        rows = build_group_topic_deliveries([(sample_job_no_topics, 2)])
        assert len(rows) == 1
        assert rows[0]["recipient_key"] == ""
        assert rows[0]["status"] == STATUS_SKIPPED
        assert rows[0]["dead_letter_reason"] == "no topics assigned"

    def test_seed_mode_marks_records_skipped(self, sample_job):
        rows = build_group_topic_deliveries([(sample_job, 1)], is_seed=True)
        assert all(r["status"] == STATUS_SKIPPED for r in rows)
        assert all(r["dead_letter_reason"] == "seed_mode" for r in rows)


# ---------------------------------------------------------------------------
# Build subscriber-DM delivery records
# ---------------------------------------------------------------------------

class TestBuildSubscriberDmDeliveries:
    def test_creates_record_for_matching_user(self, sample_job):
        users = [{"id": 1, "telegram_id": 42}]
        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True}
        ]
        blacklist = {"companies": [], "keywords": []}

        with patch("core.delivery_queue.db._fetchall", return_value=users), \
             patch("core.delivery_queue.db.get_user_alerts", return_value=alerts), \
             patch("core.delivery_queue.db.get_blacklist", return_value=blacklist):
            rows = build_subscriber_dm_deliveries([(sample_job, 1)])

        assert len(rows) == 1
        assert rows[0]["recipient_key"] == "42"
        assert rows[0]["delivery_type"] == DELIVERY_TYPE_SUBSCRIBER_DM
        assert rows[0]["status"] == STATUS_PENDING

    def test_skips_disabled_dm_alert(self, sample_job):
        users = [{"id": 1, "telegram_id": 42}]
        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": False}
        ]
        blacklist = {"companies": [], "keywords": []}

        with patch("core.delivery_queue.db._fetchall", return_value=users), \
             patch("core.delivery_queue.db.get_user_alerts", return_value=alerts), \
             patch("core.delivery_queue.db.get_blacklist", return_value=blacklist):
            rows = build_subscriber_dm_deliveries([(sample_job, 1)])

        assert rows == []

    def test_blacklist_blocks_record(self, sample_job):
        users = [{"id": 1, "telegram_id": 42}]
        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True}
        ]
        blacklist = {"companies": ["acme"], "keywords": []}

        with patch("core.delivery_queue.db._fetchall", return_value=users), \
             patch("core.delivery_queue.db.get_user_alerts", return_value=alerts), \
             patch("core.delivery_queue.db.get_blacklist", return_value=blacklist):
            rows = build_subscriber_dm_deliveries([(sample_job, 1)])

        assert rows == []

    def test_one_dm_per_user_job_even_if_multiple_alerts_match(self, sample_job):
        users = [{"id": 1, "telegram_id": 42}]
        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True},
            {"position": 2, "topics": ["egypt"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True},
        ]
        blacklist = {"companies": [], "keywords": []}

        with patch("core.delivery_queue.db._fetchall", return_value=users), \
             patch("core.delivery_queue.db.get_user_alerts", return_value=alerts), \
             patch("core.delivery_queue.db.get_blacklist", return_value=blacklist):
            rows = build_subscriber_dm_deliveries([(sample_job, 1)])

        assert len(rows) == 1

    def test_seed_mode_marks_records_skipped(self, sample_job):
        users = [{"id": 1, "telegram_id": 42}]
        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True}
        ]
        blacklist = {"companies": [], "keywords": []}

        with patch("core.delivery_queue.db._fetchall", return_value=users), \
             patch("core.delivery_queue.db.get_user_alerts", return_value=alerts), \
             patch("core.delivery_queue.db.get_blacklist", return_value=blacklist):
            rows = build_subscriber_dm_deliveries([(sample_job, 1)], is_seed=True)

        assert len(rows) == 1
        assert rows[0]["status"] == STATUS_SKIPPED
        assert rows[0]["dead_letter_reason"] == "seed_mode"


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

class TestEnqueueJobDeliveries:
    def test_inserts_group_and_dm_records(self, sample_job):
        users = [{"id": 1, "telegram_id": 42}]
        alerts = [
            {"position": 1, "topics": ["backend"], "seniority": [], "locations": [],
             "sources": [], "keywords": [], "min_salary": None, "dm_enabled": True}
        ]
        blacklist = {"companies": [], "keywords": []}

        inserted = []

        def fake_execute_values(cur, sql, rows, **kwargs):
            inserted.extend(rows)
            return [(i,) for i in range(len(rows))]

        with patch("core.delivery_queue.db._fetchall", return_value=users), \
             patch("core.delivery_queue.db.get_user_alerts", return_value=alerts), \
             patch("core.delivery_queue.db.get_blacklist", return_value=blacklist), \
             patch("core.delivery_queue.psycopg2.extras.execute_values", side_effect=fake_execute_values), \
             patch("core.delivery_queue.db._get_conn") as mock_conn:
            mock_cur = MagicMock()
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            stats = enqueue_job_deliveries([(sample_job, 1)])

        group_rows = [r for r in inserted if r["delivery_type"] == DELIVERY_TYPE_GROUP_TOPIC]
        dm_rows = [r for r in inserted if r["delivery_type"] == DELIVERY_TYPE_SUBSCRIBER_DM]
        assert len(group_rows) == 2
        assert len(dm_rows) == 1
        assert stats["group_topic_queued"] == 2
        assert stats["subscriber_dm_queued"] == 1


# ---------------------------------------------------------------------------
# Claim / mark sent / mark failed
# ---------------------------------------------------------------------------

class TestClaimPendingDeliveries:
    def test_claim_returns_rows_and_sets_processing(self):
        now = datetime.now(timezone.utc)
        rows = [
            {"id": 1, "job_id": 10, "delivery_type": DELIVERY_TYPE_GROUP_TOPIC,
             "recipient_key": "backend", "status": STATUS_PENDING,
             "next_attempt_at": now, "attempts": 0},
        ]

        def fake_execute(sql, params):
            # We only verify the function runs the UPDATE ... RETURNING via _get_conn.
            return None

        with patch("core.delivery_queue.db._get_conn") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = rows
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            claimed = claim_pending_deliveries(10, worker_id="test-worker")

        assert claimed == rows
        mock_cur.execute.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "FOR UPDATE SKIP LOCKED" in sql
        assert "status = %s" in sql


class TestMarkDeliverySent:
    def test_updates_status_and_message_id(self):
        with patch("core.delivery_queue.db._execute") as mock_exec:
            mark_delivery_sent(5, "test-worker", 123)
            assert mock_exec.called
            # First call: the delivery status update; second: jobs.sent_at update.
            first_params = mock_exec.call_args_list[0][0][1]
            assert STATUS_SENT in first_params
            assert 123 in first_params
            assert 5 in first_params
            assert "test-worker" in first_params


class TestMarkDeliveryFailed:
    def test_retryable_failure_sets_pending_with_backoff(self):
        with patch("core.delivery_queue.db._fetchone", return_value={"attempts": 1}), \
             patch("core.delivery_queue.db._execute") as mock_exec:
            mark_delivery_failed(5, "test-worker", "network error", retryable=True)
            params = mock_exec.call_args[0][1]
            assert STATUS_PENDING in params
            assert "network error" in params

    def test_permanent_failure_sets_dead_letter(self):
        with patch("core.delivery_queue.db._fetchone", return_value={"attempts": 1}), \
             patch("core.delivery_queue.db._execute") as mock_exec:
            mark_delivery_failed(5, "test-worker", "bot was blocked", retryable=False)
            params = mock_exec.call_args[0][1]
            assert STATUS_DEAD_LETTER in params

    def test_exhausted_retries_dead_letters(self):
        with patch("core.delivery_queue.db._fetchone", return_value={"attempts": 5}), \
             patch("core.delivery_queue.db._execute") as mock_exec:
            mark_delivery_failed(5, "test-worker", "network error", retryable=True, max_attempts=5)
            params = mock_exec.call_args[0][1]
            assert STATUS_DEAD_LETTER in params
            assert "retry_exhausted" in params


class TestBackoff:
    def test_backoff_doubles_each_attempt(self):
        t1 = _next_attempt_at(1, 30)
        t2 = _next_attempt_at(2, 30)
        t3 = _next_attempt_at(3, 30)
        assert t2 - t1 < t3 - t2
        assert (t2 - t1).total_seconds() == pytest.approx(30, rel=0.1)
        assert (t3 - t2).total_seconds() == pytest.approx(60, rel=0.1)


class TestReleaseDeliveryToPending:
    def test_decrements_attempts(self):
        with patch("core.delivery_queue.db._execute") as mock_exec:
            release_delivery_to_pending(5)
            sql = mock_exec.call_args[0][0]
            assert "attempts = GREATEST(attempts - 1, 0)" in sql


class TestRecoverStaleDeliveries:
    def test_returns_to_pending_when_retries_remain(self):
        stale = [{"id": 1, "attempts": 1}]
        with patch("core.delivery_queue.db._get_conn") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = stale
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            stats = recover_stale_deliveries(lease_seconds=600, max_attempts=5)
            assert stats == {"recovered": 1, "dead_lettered": 0}
            # The UPDATE call should set status to pending.
            update_sql = mock_cur.execute.call_args_list[1][0][0]
            assert "SET status = %s" in update_sql
            update_params = mock_cur.execute.call_args_list[1][0][1]
            assert STATUS_PENDING in update_params

    def test_dead_letters_when_retries_exhausted(self):
        stale = [{"id": 1, "attempts": 5}]
        with patch("core.delivery_queue.db._get_conn") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = stale
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
            stats = recover_stale_deliveries(lease_seconds=600, max_attempts=5)
            assert stats == {"recovered": 0, "dead_lettered": 1}
            update_sql = mock_cur.execute.call_args_list[1][0][0]
            assert "SET status = %s" in update_sql
            update_params = mock_cur.execute.call_args_list[1][0][1]
            assert STATUS_DEAD_LETTER in update_params


class TestReplayDeadLetter:
    def test_replays_dead_letter(self):
        with patch("core.delivery_queue.db._execute", return_value={"id": 7}) as mock_exec:
            ok = replay_dead_letter(7)
            assert ok is True
            params = mock_exec.call_args[0][1]
            assert STATUS_PENDING in params
            assert 7 in params


class TestGetDeliveryStats:
    def test_aggregates_status_counts(self):
        rows = [
            {"status": STATUS_PENDING, "delivery_type": DELIVERY_TYPE_GROUP_TOPIC, "count": 3},
            {"status": STATUS_SENT, "delivery_type": DELIVERY_TYPE_GROUP_TOPIC, "count": 2},
            {"status": STATUS_PENDING, "delivery_type": DELIVERY_TYPE_SUBSCRIBER_DM, "count": 5},
        ]
        with patch("core.delivery_queue.db._fetchall", return_value=rows):
            stats = get_delivery_stats()
        assert stats["pending"] == 8
        assert stats["sent"] == 2
        assert stats["group_topic"]["pending"] == 3
        assert stats["subscriber_dm"]["pending"] == 5
