"""Offline startup gates for optional non-Alpaca network warmups."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import anyio
import pytest


class _Scheduler:
    def __init__(self, events):
        self.events = events

    def reconcile_from_config(self, *, run_immediately):
        self.events.append(("scheduler.reconcile", run_immediately))

    def stop(self):
        self.events.append("scheduler.stop")


class _SystemConfig:
    def __init__(self, *, runtime_scheduler):
        self.runtime_scheduler = runtime_scheduler


async def _exercise_startup_network_gates(stock_enabled, akshare_enabled):
    from api import app as app_module

    events = []
    app = SimpleNamespace(state=SimpleNamespace())
    config = SimpleNamespace(
        stock_index_remote_update_enabled=stock_enabled,
        akshare_name_cache_warmup_enabled=akshare_enabled,
        schedule_run_immediately=False,
    )
    schedule = Mock(side_effect=lambda _app, reason: events.append(("stock", reason)))
    warmup = Mock(side_effect=lambda: events.append("akshare"))

    with patch.object(app_module, "RuntimeSchedulerService", side_effect=lambda **_: _Scheduler(events)), \
         patch.object(app_module, "SystemConfigService", _SystemConfig), \
         patch("src.config.get_config", return_value=config), \
         patch.object(app_module, "_schedule_stock_index_background_refresh", schedule), \
         patch("src.services.name_to_code_resolver.warmup_akshare_cache", warmup):
        async with app_module.app_lifespan(app):
            assert ("stock", "startup") in events if stock_enabled else ("stock", "startup") not in events
            assert "akshare" in events if akshare_enabled else "akshare" not in events

    assert events[-1] == "scheduler.stop"
    assert schedule.call_count == int(stock_enabled)
    assert warmup.call_count == int(akshare_enabled)


@pytest.mark.parametrize("stock_enabled", [False, True])
@pytest.mark.parametrize("akshare_enabled", [False, True])
def test_startup_network_gates_are_independent(stock_enabled, akshare_enabled):
    anyio.run(_exercise_startup_network_gates, stock_enabled, akshare_enabled)


async def _exercise_startup_cleanup():
    from api import app as app_module

    events = []
    app = SimpleNamespace(state=SimpleNamespace())
    config = SimpleNamespace(
        stock_index_remote_update_enabled=False,
        akshare_name_cache_warmup_enabled=False,
        schedule_run_immediately=False,
    )
    with patch.object(app_module, "RuntimeSchedulerService", side_effect=lambda **_: _Scheduler(events)), \
         patch.object(app_module, "SystemConfigService", _SystemConfig), \
         patch("src.config.get_config", return_value=config), \
         patch.object(app_module, "_schedule_stock_index_background_refresh") as schedule, \
         patch("src.services.name_to_code_resolver.warmup_akshare_cache") as warmup:
        async with app_module.app_lifespan(app):
            pass

    schedule.assert_not_called()
    warmup.assert_not_called()
    assert events == [("scheduler.reconcile", False), "scheduler.stop"]


def test_startup_cleanup_cancels_only_scheduled_stock_refresh():
    anyio.run(_exercise_startup_cleanup)
