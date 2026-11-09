from __future__ import annotations

import asyncio
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

from src.config.event_reminders import EventRemindersSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.event_reminders.cron_scheduler import build_cron_expression


def _stub_forms() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("dev-webhook-secret"),
        revision_form_token_secret=SecretStr("dev-revision-secret"),
        loading_form_token_secret=SecretStr("dev-loading-secret"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "dev-warehouse-inventory-secret",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _disabled_settings() -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="",
        ),
        event_reminders=EventRemindersSettings.model_construct(worker_enabled=False),
    )


def _enabled_settings() -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="creds.json",
        ),
        event_reminders=EventRemindersSettings.model_construct(
            worker_enabled=True,
            telegram_bot_token=SecretStr("report-token"),
            telegram_chat_id=-1001,
            alert_telegram_chat_id=-1002,
            alert_telegram_bot_token=None,
            tz="Asia/Yekaterinburg",
            hours=(11, 8),
            lead_days=(1, 3),
            spreadsheet_id="ss-id",
            sheet_id=42,
        ),
    )


def test_cron_hours_from_env_list() -> None:
    assert build_cron_expression(hours=(8, 11)) == "0 8,11 * * *"
    assert build_cron_expression(hours=(11, 8)) == "0 8,11 * * *"


def test_disabled_worker_idles_without_mongo() -> None:
    from src.infrastructure.composition.wiring.assemble_event_reminders_worker import (
        assemble_event_reminders_worker,
    )
    from src.infrastructure.event_reminders.worker_runtime import EventRemindersWorkerRuntime

    class _Scheduler:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    scheduler = _Scheduler()
    runtime = EventRemindersWorkerRuntime(
        enabled=False,
        scheduler=scheduler,
        idle_poll_seconds=60.0,
    )

    async def _run_once() -> None:
        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0)
        runtime.request_shutdown()
        await task

    asyncio.run(_run_once())
    assert scheduler.started is False
    assert scheduler.stopped is True

    container = assemble_event_reminders_worker(_disabled_settings())
    assert container.runtime.enabled is False
    assert (
        not hasattr(container, "persistence")
        or getattr(container, "persistence", None) is None
        or getattr(getattr(container, "persistence", None), "mongo_client", None) is None
    )
    container.close()


def test_enabled_wire_registers_scheduler_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.composition.wiring import wire_event_reminders_worker as wire_mod
    from src.infrastructure.composition.wiring.assemble_event_reminders_worker import (
        assemble_event_reminders_worker,
    )

    added: list[dict[str, Any]] = []

    class _FakeBackend:
        def __init__(self) -> None:
            self.started = False

        def add_cron_job(
            self,
            *,
            crontab: str,
            timezone: ZoneInfo,
            callback: object,
            job_id: str,
        ) -> None:
            added.append(
                {
                    "crontab": crontab,
                    "timezone": str(timezone),
                    "job_id": job_id,
                    "callback": callback,
                }
            )

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.started = False

    fake_backend = _FakeBackend()
    monkeypatch.setattr(
        wire_mod,
        "ApschedulerEventRemindersBackend",
        lambda: fake_backend,
    )

    class _Sheet:
        def read_event_rows(self) -> list[list[str]]:
            return [["Дата", "Локация", "Комментарий"]]

    class _Reminder:
        def send_plain_pre_content(self, text: str) -> None:
            return None

    class _Alert:
        def send_text(self, text: str) -> None:
            return None

    monkeypatch.setattr(
        wire_mod,
        "GoogleSheetsEventSource",
        lambda **kwargs: _Sheet(),
    )
    monkeypatch.setattr(
        wire_mod,
        "HttpReminderNotifier",
        lambda **kwargs: _Reminder(),
    )
    monkeypatch.setattr(
        wire_mod,
        "HttpAlertNotifier",
        lambda **kwargs: _Alert(),
    )

    settings = _enabled_settings()
    # assemble must not require MONGODB_URI
    container = assemble_event_reminders_worker(settings)
    assert container.runtime.enabled is True

    container.runtime.scheduler.start()
    assert added
    assert added[0]["crontab"] == "0 8,11 * * *"
    assert added[0]["timezone"] == "Asia/Yekaterinburg"
    assert "event_reminders" in added[0]["job_id"]
    container.close()


def test_event_reminders_container_has_no_app_surface() -> None:
    from src.infrastructure.composition.event_reminders_worker_container import (
        EventRemindersWorkerContainer,
    )
    from src.infrastructure.event_reminders.worker_runtime import EventRemindersWorkerRuntime

    class _Scheduler:
        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    runtime = EventRemindersWorkerRuntime(enabled=False, scheduler=_Scheduler())
    container = EventRemindersWorkerContainer(runtime=runtime)
    assert hasattr(container, "run")
    assert hasattr(container, "close")
    assert not hasattr(container, "api_app")
    assert not hasattr(container, "dispatcher")
