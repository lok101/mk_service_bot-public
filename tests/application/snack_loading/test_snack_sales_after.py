from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.snack_loading import DeployMappedSnackSalesAfter
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore
from src.infrastructure.testing.snack_loading_fakes import InMemoryKitMatrixDeployMapStore

_AFTER = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_MACHINE = "514"


def _sale(**kwargs: object) -> MachineSale:
    base: dict[str, object] = dict(
        source_id="s1",
        machine_id=MachineId("m1"),
        product_code="SKU1",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
        sale_kind="snack",
        kit_matrix_id=42,
        kit_line_number=1,
        machine_code=_MACHINE,
        resolve_status="resolved",
    )
    base.update(kwargs)
    return MachineSale(**base)  # type: ignore[arg-type]


def test_snack_sales_after_returns_only_resolved_after_anchor() -> None:
    sales_store = InMemoryMachineSalesStore()
    deploy_map = InMemoryKitMatrixDeployMapStore()
    deploy_map.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code=_MACHINE,
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    sales_store.insert_if_absent(
        _sale(source_id="resolved-after", resolve_status="resolved"),
    )
    sales_store.insert_if_absent(
        _sale(
            source_id="unresolved-after",
            resolve_status="unresolved_matrix",
            occurred_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
        ),
    )
    sales_store.insert_if_absent(
        _sale(
            source_id="resolved-at-anchor",
            occurred_at=_AFTER,
            resolve_status="resolved",
        ),
    )
    port = DeployMappedSnackSalesAfter(sales_store=sales_store, deploy_map=deploy_map)

    rows = port.query(_MACHINE, _AFTER)

    assert len(rows) == 1
    assert rows[0].source_id == "resolved-after"
    assert rows[0].logical_matrix_name == "SnackA"
    assert rows[0].line_number == 1
    assert rows[0].resolve_status == "resolved"


def test_snack_sales_after_logs_when_deploy_map_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sales_store = InMemoryMachineSalesStore()
    deploy_map = InMemoryKitMatrixDeployMapStore()
    sales_store.insert_if_absent(
        _sale(source_id="orphan-resolved", kit_matrix_id=99),
    )
    port = DeployMappedSnackSalesAfter(sales_store=sales_store, deploy_map=deploy_map)

    with caplog.at_level(logging.WARNING):
        rows = port.query(_MACHINE, _AFTER)

    assert rows == ()
    record = next(
        r for r in caplog.records if r.getMessage() == "snack_inventory_replay_deploy_map_skip"
    )
    assert record.source_id == "orphan-resolved"
    assert record.machine_code == _MACHINE
    assert record.kit_matrix_id == 99
    assert record.mapped_machine_code is None
