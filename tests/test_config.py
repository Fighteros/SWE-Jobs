"""
Tests that delivery-queue configuration has safe defaults when env vars are absent.
"""

import os
import importlib

import pytest

import core.config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove delivery-related env vars before each test."""
    for key in [
        "FETCH_INTERVAL_MINUTES",
        "DELIVERY_INTERVAL_SECONDS",
        "DELIVERY_BATCH_SIZE",
        "DELIVERY_MAX_ATTEMPTS",
        "DELIVERY_RETRY_BASE_SECONDS",
        "DELIVERY_PROCESSING_LEASE_SECONDS",
        "DELIVERY_IDLE_SLEEP_SECONDS",
        "DELIVERY_MAX_CYCLE_SECONDS",
        "DM_MAX_PER_USER_PER_WINDOW",
        "DM_RATE_WINDOW_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_delivery_defaults_when_unset():
    importlib.reload(core.config)

    assert core.config.FETCH_INTERVAL_MINUTES == 5
    assert core.config.DELIVERY_INTERVAL_SECONDS == 60
    assert core.config.DELIVERY_BATCH_SIZE == 50
    assert core.config.DELIVERY_MAX_ATTEMPTS == 5
    assert core.config.DELIVERY_RETRY_BASE_SECONDS == 30
    assert core.config.DELIVERY_PROCESSING_LEASE_SECONDS == 600
    assert core.config.DELIVERY_IDLE_SLEEP_SECONDS == 10
    assert core.config.DELIVERY_MAX_CYCLE_SECONDS == 50
    assert core.config.DM_MAX_PER_USER_PER_WINDOW == 20
    assert core.config.DM_RATE_WINDOW_SECONDS == 3600


def test_delivery_env_overrides(clean_env, monkeypatch):
    monkeypatch.setenv("DELIVERY_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("DELIVERY_BATCH_SIZE", "25")
    monkeypatch.setenv("DELIVERY_MAX_ATTEMPTS", "3")

    importlib.reload(core.config)

    assert core.config.DELIVERY_INTERVAL_SECONDS == 120
    assert core.config.DELIVERY_BATCH_SIZE == 25
    assert core.config.DELIVERY_MAX_ATTEMPTS == 3
