from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from tests.application.machine_pnl.fakes import InMemoryUnitCostCatalog
from tests.config.test_machine_pnl_settings import _stub_required_app_env

from src.application.machine_pnl.location_rent_sheet import RowsLocationRentCatalog
from src.application.machine_pnl.rent_ports import FixtureLocationRentCatalog
from src.application.outbox.composite_terminal_failure_notifier import (
    CompositeOutboxTerminalFailureNotifier,
)
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.infrastructure.composition.adapters.machine_pnl_ops_alerter import (
    NoOpMachinePnlOpsAlerter,
    TelegramMachinePnlOpsAlerter,
    build_machine_pnl_ops_alerter,
)
from src.infrastructure.composition.adapters.outbox_failure_notifier import (
    build_outbox_failure_notifier,
)
from src.infrastructure.composition.adapters.rent_accountant_alerter import (
    NoOpRentAccountantAlerter,
)
from src.infrastructure.composition.factories import machine_pnl as machine_pnl_factory
from src.infrastructure.composition.factories.machine_pnl import (
    build_machine_pnl_period_handler,
)
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.outbox.event_deserializer import OutboxEventDeserializerAdapter


class _CapturingHandler:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_machine_pnl_handler_wires_rent_occupancy_and_accountant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "true")
    monkeypatch.setenv("MACHINE_PNL_UNIT_COST_SPREADSHEET_ID", "sheet-ss")
    monkeypatch.setenv("MACHINE_PNL_UNIT_COST_SHEET_ID", "1")
    monkeypatch.setenv("MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID", "sheet-ss")
    monkeypatch.setenv("MACHINE_PNL_GLOBAL_OPEX_SHEET_ID", "10")
    monkeypatch.setenv("MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID", "sheet-ss")
    monkeypatch.setenv("MACHINE_PNL_LOCATION_RENT_SHEET_ID", "20")
    monkeypatch.setenv("MACHINE_PNL_RENT_PENDING_RETRY_HOURS", "36")
    monkeypatch.setenv("MACHINE_PNL_RENT_PENDING_MAX_ATTEMPTS", "5")
    monkeypatch.delenv("MACHINE_PNL_RENT_ACCOUNTANT_CHAT_ID", raising=False)

    catalog = InMemoryUnitCostCatalog(_default=Decimal("10.00"))
    monkeypatch.setattr(
        machine_pnl_factory,
        "build_unit_cost_catalog_loader",
        lambda settings: lambda: catalog,
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "build_period_pnl_store",
        lambda settings, *, client=None: object(),
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "SettlementResidualSessionReader",
        lambda settlement_repository: object(),
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "EventStoreServiceFactCounter",
        lambda event_store: object(),
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "as_period_snapshot_reader",
        lambda repo: object(),
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "load_global_opex_sheet_rows",
        lambda **kwargs: [
            [
                "valid_from",
                "labor_rate_global",
                "acquiring_percent",
                "acquiring_fee_per_sale",
                "terminal_monthly",
            ],
            ["2026-01-01", "50", "2,5", "0,2", "900"],
        ],
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "load_location_rent_sheet_rows",
        lambda **kwargs: [
            [
                "Сумма",
                "Процент",
                "Id локации",
                "Id ТТ",
                "Имя",
                "Дата установки",
                "Дата снятия",
            ],
            ["100", "", "loc-1", "101", "n", "01.05.2026", ""],
        ],
    )
    monkeypatch.setattr(machine_pnl_factory, "MachinePnlPeriodHandler", _CapturingHandler)

    settings = Settings()
    # Bypass beartype param checks on Protocol stubs; exercise factory body.
    build = getattr(
        build_machine_pnl_period_handler,
        "__wrapped__",
        build_machine_pnl_period_handler,
    )
    handler = build(
        settings,
        reconciliation_repo=object(),
        machine_sales_store=object(),
        settlement_repository=object(),
        event_store=object(),
    )

    assert isinstance(handler, _CapturingHandler)
    assert callable(handler.kwargs["load_opex_params"])
    assert callable(handler.kwargs["load_location_rent"])
    rent = handler.kwargs["load_location_rent"]()
    assert isinstance(rent, RowsLocationRentCatalog)
    assert not isinstance(rent, FixtureLocationRentCatalog)
    assert rent.list_for_machine(MachineId("101"))[0].rent_monthly == Decimal("100")
    assert isinstance(handler.kwargs["rent_accountant_alerter"], NoOpRentAccountantAlerter)
    assert handler.kwargs["rent_pending_retry_hours"] == 36
    assert handler.kwargs["rent_pending_max_attempts"] == 5


def test_machine_pnl_ops_alerter_noop_when_alert_chat_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.delenv("MACHINE_PNL_ALERT_CHAT_ID", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "bot-token")

    alerter = build_machine_pnl_ops_alerter(Settings())
    assert isinstance(alerter, NoOpMachinePnlOpsAlerter)
    alerter.notify_terminal_failure(
        handler_id="machine_pnl_period",
        error_message="rent terms pending",
        period_id="p-1",
        event_id="machine_pnl:p-1",
    )


def test_machine_pnl_ops_alerter_telegram_when_alert_chat_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MACHINE_PNL_ALERT_CHAT_ID", "999001")
    monkeypatch.setenv("BOT_TOKEN", "bot-token")

    alerter = build_machine_pnl_ops_alerter(Settings())
    assert isinstance(alerter, TelegramMachinePnlOpsAlerter)


def test_build_outbox_failure_notifier_is_composite_with_ops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.delenv("MACHINE_PNL_ALERT_CHAT_ID", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "bot-token")

    class _FormWf:
        async def notify(self, message: Any) -> None:
            return None

    notifier = build_outbox_failure_notifier(
        Settings(),
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=_FormWf(),
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    assert isinstance(notifier, CompositeOutboxTerminalFailureNotifier)
    assert isinstance(notifier.primary, OutboxTerminalFailureNotifier)
    assert isinstance(notifier.machine_pnl_ops, NoOpMachinePnlOpsAlerter)
