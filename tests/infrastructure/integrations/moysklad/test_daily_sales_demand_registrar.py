from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.application.form_submissions.ports import ExternalSideEffectInProgressError
from src.application.inventory_reconciliation.ms_registrar_ports import (
    RegistrarPermanentError,
    RegistrarTransientError,
    StockDocumentLine,
)
from src.infrastructure.integrations.moysklad.daily_sales_demand_registrar import (
    MoySkladDailySalesDemandRegistrar,
)
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladConnectionError,
    MoySkladRequestError,
    MoySkladValidationError,
)
from src.infrastructure.memory_side_effects import InMemoryExternalSideEffectRegistry

ORG = uuid4()
PROJECT = uuid4()
CHANNEL = uuid4()
AGENT = uuid4()
STORE = uuid4()
_MOMENT = datetime(2026, 8, 9, 23, 55, tzinfo=UTC)
_SALES_DAY = date(2026, 8, 9)


def _registrar(
    client: FakeMoySkladClient,
    *,
    registry: InMemoryExternalSideEffectRegistry | None = None,
) -> MoySkladDailySalesDemandRegistrar:
    return MoySkladDailySalesDemandRegistrar(
        client=client,
        organization_id=ORG,
        demand_agent_id=AGENT,
        side_effect_registry=registry or InMemoryExternalSideEffectRegistry(),
    )


def test_daily_registrar_has_no_product_spec_resolver() -> None:
    fields = {f.name for f in dataclasses.fields(MoySkladDailySalesDemandRegistrar)}
    assert "product_spec_by_code" not in fields


def test_daily_demand_quantity_not_scaled_by_factor() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    registrar = MoySkladDailySalesDemandRegistrar(
        client=client,
        organization_id=ORG,
        demand_agent_id=AGENT,
        side_effect_registry=InMemoryExternalSideEffectRegistry(),
    )
    asyncio.run(
        registrar.register_daily_sales_demand(
            warehouse_code="M1",
            lines=[
                StockDocumentLine(product_code="P1", quantity=Decimal("1000"), price_kop=100),
            ],
            moment=_MOMENT,
            sales_day=_SALES_DAY,
            sales_channel_id=CHANNEL,
            project_id=PROJECT,
        ),
    )
    rows = client.posted_payloads[0]["positions"]["rows"]  # type: ignore[index]
    assert rows[0]["quantity"] == 1000


def test_daily_demand_external_code_format() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    registrar = _registrar(client)
    expected = "mk-service-bot:daily-sales-demand:M1:2026-08-09"

    asyncio.run(
        registrar.register_daily_sales_demand(
            warehouse_code="M1",
            lines=[StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100)],
            moment=_MOMENT,
            sales_day=_SALES_DAY,
            sales_channel_id=CHANNEL,
            project_id=PROJECT,
        ),
    )

    assert len(client.posted_payloads) == 1
    assert client.posted_payloads[0]["externalCode"] == expected

    asyncio.run(
        registrar.register_daily_sales_demand(
            warehouse_code="M1",
            lines=[StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100)],
            moment=_MOMENT,
            sales_day=_SALES_DAY,
            sales_channel_id=CHANNEL,
            project_id=PROJECT,
        ),
    )
    assert len(client.posted_payloads) == 1


def test_daily_demand_passes_channel_project_agent_and_price() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    registrar = _registrar(client)

    asyncio.run(
        registrar.register_daily_sales_demand(
            warehouse_code="M1",
            lines=[
                StockDocumentLine(product_code="P1", quantity=Decimal("2"), price_kop=12500),
            ],
            moment=_MOMENT,
            sales_day=_SALES_DAY,
            sales_channel_id=CHANNEL,
            project_id=PROJECT,
        ),
    )

    body = client.posted_payloads[-1]
    assert "agent" in body
    assert "project" in body
    assert "salesChannel" in body
    agent = body["agent"]
    assert isinstance(agent, dict)
    assert agent["meta"]["href"].endswith(f"/counterparty/{AGENT}")
    project = body["project"]
    assert isinstance(project, dict)
    assert project["meta"]["href"].endswith(f"/project/{PROJECT}")
    channel = body["salesChannel"]
    assert isinstance(channel, dict)
    assert channel["meta"]["href"].endswith(f"/saleschannel/{CHANNEL}")
    rows = body["positions"]["rows"]  # type: ignore[index]
    assert rows[0]["price"] == 12500
    assert rows[0]["quantity"] == 2


def test_registrar_maps_validation_error_to_permanent() -> None:
    client = FakeMoySkladClient(
        store_id_by_code_errors={
            "X": MoySkladValidationError("Склад с кодом 'X' не найден."),
        },
    )
    registrar = _registrar(client)
    with pytest.raises(RegistrarPermanentError, match="Склад с кодом 'X' не найден"):
        asyncio.run(
            registrar.register_daily_sales_demand(
                warehouse_code="X",
                lines=[
                    StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100),
                ],
                moment=_MOMENT,
                sales_day=_SALES_DAY,
                sales_channel_id=CHANNEL,
                project_id=PROJECT,
            ),
        )


def test_registrar_maps_connection_error_to_transient() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    client.raise_after_post = MoySkladConnectionError("timed out")
    registrar = _registrar(client)
    with pytest.raises(RegistrarTransientError, match="timed out") as exc_info:
        asyncio.run(
            registrar.register_daily_sales_demand(
                warehouse_code="M1",
                lines=[
                    StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100),
                ],
                moment=_MOMENT,
                sales_day=_SALES_DAY,
                sales_channel_id=CHANNEL,
                project_id=PROJECT,
            ),
        )
    assert not isinstance(exc_info.value, MoySkladConnectionError)
    assert isinstance(exc_info.value.__cause__, MoySkladConnectionError)


def test_registrar_maps_in_progress_to_transient() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    registry = InMemoryExternalSideEffectRegistry()
    external_code = "mk-service-bot:daily-sales-demand:M1:2026-08-09"
    registry.claim(
        provider="moysklad",
        operation="demand",
        idempotency_key=external_code,
        external_code=external_code,
    )
    registrar = _registrar(client, registry=registry)
    with pytest.raises(RegistrarTransientError, match="already processing") as exc_info:
        asyncio.run(
            registrar.register_daily_sales_demand(
                warehouse_code="M1",
                lines=[
                    StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100),
                ],
                moment=_MOMENT,
                sales_day=_SALES_DAY,
                sales_channel_id=CHANNEL,
                project_id=PROJECT,
            ),
        )
    assert isinstance(exc_info.value.__cause__, ExternalSideEffectInProgressError)
    assert client.posted_payloads == []


def test_registrar_does_not_wrap_api_error() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    client.next_post_error = MoySkladRequestError(429, {"errors": [{"code": 1072}]})
    registrar = _registrar(client)
    with pytest.raises(MoySkladRequestError):
        asyncio.run(
            registrar.register_daily_sales_demand(
                warehouse_code="M1",
                lines=[
                    StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100),
                ],
                moment=_MOMENT,
                sales_day=_SALES_DAY,
                sales_channel_id=CHANNEL,
                project_id=PROJECT,
            ),
        )


def test_daily_demand_recovers_without_second_post_after_timeout_once_accepted() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    registry = InMemoryExternalSideEffectRegistry()
    registrar = _registrar(client, registry=registry)
    expected_code = "mk-service-bot:daily-sales-demand:M1:2026-08-09"
    client.raise_after_post = MoySkladConnectionError("timed out")

    with pytest.raises(RegistrarTransientError, match="timed out"):
        asyncio.run(
            registrar.register_daily_sales_demand(
                warehouse_code="M1",
                lines=[
                    StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100),
                ],
                moment=_MOMENT,
                sales_day=_SALES_DAY,
                sales_channel_id=CHANNEL,
                project_id=PROJECT,
            ),
        )
    assert len(client.posted_payloads) == 1
    assert client.posted_payloads[0]["externalCode"] == expected_code

    asyncio.run(
        registrar.register_daily_sales_demand(
            warehouse_code="M1",
            lines=[
                StockDocumentLine(product_code="P1", quantity=Decimal("1"), price_kop=100),
            ],
            moment=_MOMENT,
            sales_day=_SALES_DAY,
            sales_channel_id=CHANNEL,
            project_id=PROJECT,
        ),
    )
    assert len(client.posted_payloads) == 1
    entry = registry._entries[("moysklad", "demand", expected_code)]
    assert entry["status"] == "succeeded"
