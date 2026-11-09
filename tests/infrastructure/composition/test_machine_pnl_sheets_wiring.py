from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from tests.application.machine_pnl.fakes import InMemoryUnitCostCatalog
from tests.config.test_machine_pnl_settings import _stub_required_app_env

from src.application.machine_pnl.composed_opex_params import ComposedOpExParamsCatalog
from src.application.machine_pnl.location_rent_sheet import RowsLocationRentCatalog
from src.application.machine_pnl.rent_ports import FixtureLocationRentCatalog
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.infrastructure.composition.adapters.rent_accountant_alerter import (
    NoOpRentAccountantAlerter,
)
from src.infrastructure.composition.factories import machine_pnl as machine_pnl_factory
from src.infrastructure.composition.factories.machine_pnl import (
    build_machine_pnl_period_handler,
)


class _CapturingHandler:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


_GLOBAL_HEADER = [
    "valid_from",
    "labor_rate_global",
    "acquiring_percent",
    "acquiring_fee_per_sale",
    "terminal_monthly",
]
_RENT_HEADER = [
    "Сумма",
    "Процент",
    "Id локации",
    "Id ТТ",
    "Имя",
    "Дата установки",
    "Дата снятия",
]


def test_machine_pnl_handler_wires_sheets_global_and_rent_loaders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: ENABLED + four sheet ids → Callables return Sheets catalogs (not empty Fixture SoT)
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "true")
    monkeypatch.setenv("MACHINE_PNL_UNIT_COST_SPREADSHEET_ID", "sheet-ss")
    monkeypatch.setenv("MACHINE_PNL_UNIT_COST_SHEET_ID", "1")
    monkeypatch.setenv("MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID", "sheet-ss")
    monkeypatch.setenv("MACHINE_PNL_GLOBAL_OPEX_SHEET_ID", "10")
    monkeypatch.setenv("MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID", "sheet-ss")
    monkeypatch.setenv("MACHINE_PNL_LOCATION_RENT_SHEET_ID", "20")
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
        lambda **kwargs: [_GLOBAL_HEADER, ["2026-01-01", "50", "2,5", "0,2", "900"]],
    )
    monkeypatch.setattr(
        machine_pnl_factory,
        "load_location_rent_sheet_rows",
        lambda **kwargs: [_RENT_HEADER, ["100", "", "loc-1", "101", "n", "01.05.2026", ""]],
    )
    monkeypatch.setattr(machine_pnl_factory, "MachinePnlPeriodHandler", _CapturingHandler)

    settings = Settings()
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
    opex = handler.kwargs["load_opex_params"]()
    rent = handler.kwargs["load_location_rent"]()
    assert isinstance(opex, ComposedOpExParamsCatalog)
    assert isinstance(rent, RowsLocationRentCatalog)
    assert not isinstance(rent, FixtureLocationRentCatalog)
    assert rent.list_for_machine(MachineId("101"))[0].rent_monthly == Decimal("100")
    assert isinstance(handler.kwargs["rent_accountant_alerter"], NoOpRentAccountantAlerter)
