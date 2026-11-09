from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.event_reminders import run_event_reminders_tick
from src.config.settings import Settings
from src.infrastructure.composition.event_reminders_worker_container import (
    EventRemindersWorkerContainer,
)
from src.infrastructure.event_reminders.cron_scheduler import (
    ApschedulerEventRemindersBackend,
    EventRemindersCronScheduler,
)
from src.infrastructure.event_reminders.sheets_source import GoogleSheetsEventSource
from src.infrastructure.event_reminders.telegram_notifiers import (
    HttpAlertNotifier,
    HttpReminderNotifier,
)
from src.infrastructure.event_reminders.worker_runtime import EventRemindersWorkerRuntime


@beartype
def wire_event_reminders_worker(settings: Settings) -> EventRemindersWorkerContainer:
    er = settings.event_reminders
    enabled = er.worker_enabled
    timezone = ZoneInfo(er.tz)

    if enabled:
        report_token = er.telegram_bot_token
        assert report_token is not None
        assert er.telegram_chat_id is not None
        assert er.alert_telegram_chat_id is not None
        assert er.sheet_id is not None
        alert_token = er.alert_telegram_bot_token or report_token

        sheet_source = GoogleSheetsEventSource(
            credentials_file=settings.google_sheets.credentials_file,
            spreadsheet_id=er.spreadsheet_id,
            sheet_id=er.sheet_id,
        )
        reminder_notifier = HttpReminderNotifier(
            bot_token=report_token.get_secret_value(),
            chat_id=er.telegram_chat_id,
        )
        alert_notifier = HttpAlertNotifier(
            bot_token=alert_token.get_secret_value(),
            chat_id=er.alert_telegram_chat_id,
        )
        lead_days = er.lead_days

        def tick_callback() -> None:
            today = datetime.now(timezone).date()
            run_event_reminders_tick(
                sheet_source=sheet_source,
                reminder_notifier=reminder_notifier,
                alert_notifier=alert_notifier,
                today=today,
                lead_days=lead_days,
            )

        scheduler: EventRemindersCronScheduler = EventRemindersCronScheduler(
            enabled=True,
            hours=er.hours,
            timezone=timezone,
            callback=tick_callback,
            backend=ApschedulerEventRemindersBackend(),
        )
    else:

        def tick_callback() -> None:
            return None

        scheduler = EventRemindersCronScheduler(
            enabled=False,
            hours=(),
            timezone=timezone,
            callback=tick_callback,
            backend=ApschedulerEventRemindersBackend(),
        )

    runtime = EventRemindersWorkerRuntime(
        enabled=enabled,
        scheduler=scheduler,
    )
    return EventRemindersWorkerContainer(runtime=runtime)
