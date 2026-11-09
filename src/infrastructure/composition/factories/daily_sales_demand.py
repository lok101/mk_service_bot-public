from __future__ import annotations

from typing import Any
from uuid import UUID

from beartype import beartype
from pymongo import MongoClient

from src.application.form_submissions.ports import ExternalSideEffectRegistry
from src.application.inventory_reconciliation import CreateDailySalesDemands
from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.inventory_reconciliation.sellable_assortment_ports import (
    SellableProductCodeCatalog,
)
from src.application.outbox.daily_sales_demand import DailySalesDemandHandler
from src.config.settings import Settings
from src.infrastructure.composition.factories.persistence import (
    build_external_side_effect_registry,
)
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.daily_sales_demand_registrar import (
    MoySkladDailySalesDemandRegistrar,
)


@beartype
def _parse_required_uuid(raw: str) -> UUID | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


@beartype
def build_daily_sales_demand_handler(
    settings: Settings,
    *,
    machine_sales_store: MachineSalesStore | object,
    moysklad_client: MoySkladClientPort | None,
    sellable_catalog: SellableProductCodeCatalog,
    side_effect_registry: ExternalSideEffectRegistry | None = None,
    client: MongoClient[dict[str, Any]] | None = None,
) -> DailySalesDemandHandler | None:
    """App dual-claim register when worker enabled and MS daily deps are wired."""
    if not settings.daily_sales_demand.worker_enabled:
        return None
    if moysklad_client is None or not settings.moysklad.is_configured:
        return None

    organization_id = _parse_required_uuid(settings.moysklad.organization_id)
    project_id = _parse_required_uuid(settings.moysklad.project_id)
    demand_agent_id = _parse_required_uuid(settings.moysklad.demand_agent_id)
    snack_channel_id = _parse_required_uuid(settings.moysklad.snack_sales_channel_id)
    if (
        organization_id is None
        or project_id is None
        or demand_agent_id is None
        or snack_channel_id is None
    ):
        return None

    registry = side_effect_registry
    if registry is None:
        registry = build_external_side_effect_registry(settings, client=client)

    registrar = MoySkladDailySalesDemandRegistrar(
        client=moysklad_client,
        organization_id=organization_id,
        demand_agent_id=demand_agent_id,
        side_effect_registry=registry,
    )
    create_demands = CreateDailySalesDemands(
        sales_store=machine_sales_store,  # type: ignore[arg-type]
        registrar=registrar,
        sellable_catalog=sellable_catalog,
        display_timezone=settings.service_calendar.display_timezone,
        project_id=project_id,
        snack_sales_channel_id=snack_channel_id,
    )
    return DailySalesDemandHandler(
        create_demands=create_demands,
        not_ready_retry_minutes=settings.daily_sales_demand.not_ready_retry_minutes,
        not_ready_max_attempts=settings.daily_sales_demand.not_ready_max_attempts,
    )
