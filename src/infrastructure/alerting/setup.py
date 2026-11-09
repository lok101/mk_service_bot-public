from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from types import TracebackType

from beartype import beartype
from pydantic import SecretStr

from src.config.settings import Settings
from src.infrastructure.alerting.telegram_log_handler import TelegramAlertHandler

_FATAL_LOGGER_NAME = "src.infrastructure.alerting.fatal"
SysExceptHook = Callable[[type[BaseException], BaseException, TracebackType | None], object]
ThreadingExceptHook = Callable[[threading.ExceptHookArgs], object]


@beartype
def _secret_value(secret: SecretStr | None) -> str:
    if secret is None:
        return ""
    return secret.get_secret_value().strip()


@beartype
def collect_redaction_secrets(settings: Settings) -> tuple[str, ...]:
    telegram = settings.telegram
    google_forms = settings.google_forms
    moysklad = settings.moysklad
    snack_loading = settings.snack_loading
    sales_monitoring = settings.sales_monitoring
    event_reminders = settings.event_reminders
    micromarket_loading = settings.micromarket_loading
    candidates = (
        telegram.bot_token.get_secret_value(),
        _secret_value(telegram.webhook_secret),
        google_forms.webhook_secret.get_secret_value(),
        google_forms.revision_form_token_secret.get_secret_value(),
        google_forms.loading_form_token_secret.get_secret_value(),
        google_forms.technician_warehouse_inventory_form_token_secret.get_secret_value(),
        moysklad.api_token.get_secret_value() if moysklad.api_token is not None else "",
        _secret_value(settings.location_roster.session_secret),
        _secret_value(settings.master_data.session_secret),
        _secret_value(settings.settlement_analysis.session_secret),
        _secret_value(settings.object_storage.s3_secret_access_key),
        _secret_value(snack_loading.inventory_form_now_token_secret),
        _secret_value(snack_loading.inventory_form_as_of_token_secret),
        _secret_value(micromarket_loading.inventory_form_now_token_secret),
        _secret_value(micromarket_loading.inventory_form_as_of_token_secret),
        _secret_value(sales_monitoring.telegram_bot_token),
        _secret_value(sales_monitoring.alert_telegram_bot_token),
        _secret_value(event_reminders.telegram_bot_token),
        _secret_value(event_reminders.alert_telegram_bot_token),
    )
    return tuple(value for value in candidates if value)


@beartype
def _emit_fatal_alert(
    handler: logging.Handler,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    logger = logging.getLogger(_FATAL_LOGGER_NAME)
    record = logger.makeRecord(
        logger.name,
        logging.ERROR,
        "(fatal)",
        0,
        "Unhandled exception",
        (),
        (exc_type, exc_value, exc_traceback),
    )
    # Sync emit: QueueListener may already be stopped in entry finally before excepthook.
    handler.emit(record)


@beartype
def _install_fatal_exception_hooks(handler: logging.Handler) -> Callable[[], None]:
    previous_sys_hook: SysExceptHook = sys.excepthook
    previous_thread_hook: ThreadingExceptHook = threading.excepthook

    def sys_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous_sys_hook(exc_type, exc_value, exc_traceback)
            return
        try:
            _emit_fatal_alert(handler, exc_type, exc_value, exc_traceback)
        except Exception:
            with suppress(Exception):
                sys.stderr.write("ops-alert fatal hook failed\n")
        previous_sys_hook(exc_type, exc_value, exc_traceback)

    def thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            previous_thread_hook(args)
            return
        try:
            if args.exc_value is not None:
                _emit_fatal_alert(
                    handler,
                    args.exc_type,
                    args.exc_value,
                    args.exc_traceback,
                )
        except Exception:
            with suppress(Exception):
                sys.stderr.write("ops-alert fatal hook failed\n")
        previous_thread_hook(args)

    sys.excepthook = sys_excepthook
    threading.excepthook = thread_excepthook

    def uninstall() -> None:
        if sys.excepthook is sys_excepthook:
            sys.excepthook = previous_sys_hook
        if threading.excepthook is thread_excepthook:
            threading.excepthook = previous_thread_hook

    return uninstall


@beartype
@dataclass(frozen=True, slots=True)
class OpsAlertLogging:
    listener: QueueListener
    _uninstall_fatal_hooks: Callable[[], None] = field(repr=False)

    @beartype
    def stop(self) -> None:
        # Keep fatal hooks installed: entry-point ``finally`` runs ``stop()`` before
        # ``sys.excepthook`` on uncaught exceptions from ``main()``. Sync emit still works.
        self.listener.stop()

    @beartype
    def restore_exception_hooks(self) -> None:
        self._uninstall_fatal_hooks()


@beartype
def configure_ops_alert_logging(settings: Settings) -> OpsAlertLogging | None:
    if settings.is_test or not settings.telegram.alerts_enabled:
        return None

    alert_chat_id = settings.telegram.alert_chat_id
    if alert_chat_id is None:
        return None

    handler = TelegramAlertHandler(
        bot_token=settings.telegram.bot_token.get_secret_value(),
        chat_id=alert_chat_id,
        environment=settings.environment,
        min_interval_seconds=settings.telegram.alert_min_interval_seconds,
        redact_values=collect_redaction_secrets(settings),
    )
    log_queue: Queue[logging.LogRecord] = Queue(-1)
    queue_handler = QueueHandler(log_queue)
    queue_handler.setLevel(logging.ERROR)
    listener = QueueListener(log_queue, handler, respect_handler_level=True)
    listener.start()

    root_logger = logging.getLogger()
    root_logger.addHandler(queue_handler)
    # uvicorn.error → uvicorn (propagate=False + own StreamHandler), so ASGI 500s
    # never reach root; attach the same queue handler directly.
    logging.getLogger("uvicorn.error").addHandler(queue_handler)

    uninstall_fatal_hooks = _install_fatal_exception_hooks(handler)
    return OpsAlertLogging(listener=listener, _uninstall_fatal_hooks=uninstall_fatal_hooks)
