from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from scripts.maintenance_cooldown_admin import _build_deps, _CliDeps, build_parser, main

from src.application.machine_operations.cooldown_bypass_admin import (
    ClearMaintenanceCooldownBypassService,
    DisableMaintenanceCooldownBypassForTodayService,
    GetMaintenanceCooldownBypassStatusService,
)
from src.config.mongodb import MongoSettings
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot

_MSK = ZoneInfo("Europe/Moscow")
_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FakeSettings:
    mongodb: MongoSettings

    def service_calendar_zone_info(self) -> ZoneInfo:
        return _MSK


class _FakeStore:
    def __init__(self) -> None:
        self.snapshot: MaintenanceCooldownBypassSnapshot | None = None

    def get_snapshot(self) -> MaintenanceCooldownBypassSnapshot | None:
        return self.snapshot

    def upsert_for_today(
        self,
        *,
        activated_at: datetime,
        reason: str | None,
        service_calendar_timezone: ZoneInfo,
    ) -> MaintenanceCooldownBypassSnapshot:
        _ = service_calendar_timezone
        self.snapshot = MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 8),
            activated_at=activated_at,
            reason=reason,
        )
        return self.snapshot

    def clear(self) -> bool:
        if self.snapshot is None:
            return False
        self.snapshot = None
        return True


_SHARED_STORE = _FakeStore()


def _fake_deps(*, checked_at: datetime | None = None) -> _CliDeps:
    store = _SHARED_STORE
    effective_checked_at = checked_at or _NOW
    return _CliDeps(
        disable_for_today=DisableMaintenanceCooldownBypassForTodayService(
            store=store,
            service_calendar_timezone=_MSK,
            service_day_end_hour=6,
        ),
        get_status=GetMaintenanceCooldownBypassStatusService(
            store=store,
            service_calendar_timezone=_MSK,
            service_day_end_hour=6,
            checked_at=effective_checked_at,
        ),
        clear=ClearMaintenanceCooldownBypassService(store=store),
    )


def test_build_parser_parses_disable_status_clear() -> None:
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)

    disable_args = parser.parse_args(["disable-for-today", "--reason", "форс-мажор"])
    assert disable_args.command == "disable-for-today"
    assert disable_args.reason == "форс-мажор"

    status_args = parser.parse_args(["status"])
    assert status_args.command == "status"

    clear_args = parser.parse_args(["clear"])
    assert clear_args.command == "clear"


def test_build_deps_exits_without_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.maintenance_cooldown_admin.get_settings",
        lambda: _FakeSettings(mongodb=MongoSettings()),
    )

    with pytest.raises(SystemExit) as exc_info:
        _build_deps()
    assert exc_info.value.code == 1


def test_main_disable_status_clear(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _SHARED_STORE.snapshot = None
    monkeypatch.setattr("scripts.maintenance_cooldown_admin._build_deps", _fake_deps)
    monkeypatch.setattr(
        "scripts.maintenance_cooldown_admin.datetime",
        type(
            "_DatetimeModule",
            (),
            {"now": staticmethod(lambda *, tz: _NOW), "UTC": UTC},
        )(),
    )

    disable_code = main(["disable-for-today", "--reason", "форс-мажор"])
    disable_output = capsys.readouterr().out
    assert disable_code == 0
    assert "active: true" in disable_output
    assert "service_date: 2026-07-08" in disable_output
    assert "reason: форс-мажор" in disable_output

    status_code = main(["status"])
    status_output = capsys.readouterr().out
    assert status_code == 0
    assert "active: true" in status_output

    clear_code = main(["clear"])
    clear_output = capsys.readouterr().out
    assert clear_code == 0
    assert "active: false" in clear_output

    inactive_clear_code = main(["clear"])
    inactive_output = capsys.readouterr()
    assert inactive_clear_code == 0
    assert "bypass not active" in inactive_output.out
