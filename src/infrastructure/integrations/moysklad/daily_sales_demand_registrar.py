from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from beartype import beartype

from src.application.form_submissions.ports import (
    ExternalSideEffectInProgressError,
    ExternalSideEffectRegistry,
)
from src.application.inventory_reconciliation.ms_registrar_ports import (
    DailySalesDemandRegistrar,
    RegistrarPermanentError,
    RegistrarTransientError,
    StockDocumentLine,
)
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladConnectionError,
    MoySkladValidationError,
)
from src.infrastructure.integrations.moysklad.idempotency import (
    execute_idempotent_moysklad_side_effect,
)
from src.infrastructure.integrations.moysklad.quantities import (
    stock_document_lines_to_as_sold_positions,
)
from src.infrastructure.integrations.moysklad.stock_document_registrar import post_stock_document

_DEMAND_ENTITY_PATH = "demand"
_DEMAND_OPERATION = "demand"


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladDailySalesDemandRegistrar(DailySalesDemandRegistrar):
    client: MoySkladClientPort
    organization_id: UUID
    demand_agent_id: UUID
    side_effect_registry: ExternalSideEffectRegistry

    @beartype
    async def register_daily_sales_demand(
        self,
        *,
        warehouse_code: str,
        lines: list[StockDocumentLine],
        moment: datetime,
        sales_day: date,
        sales_channel_id: UUID,
        project_id: UUID,
    ) -> None:
        positions = stock_document_lines_to_as_sold_positions(lines)
        external_code = (
            f"mk-service-bot:daily-sales-demand:{warehouse_code}:{sales_day.isoformat()}"
        )
        try:
            await execute_idempotent_moysklad_side_effect(
                registry=self.side_effect_registry,
                client=self.client,
                operation=_DEMAND_OPERATION,
                entity_path=_DEMAND_ENTITY_PATH,
                idempotency_key=external_code,
                external_code=external_code,
                create=lambda: post_stock_document(
                    client=self.client,
                    organization_id=self.organization_id,
                    entity_path="demand",
                    warehouse_code=warehouse_code,
                    positions=positions,
                    moment=moment,
                    external_code=external_code,
                    agent_id=self.demand_agent_id,
                    project_id=project_id,
                    sales_channel_id=sales_channel_id,
                ),
            )
        except MoySkladValidationError as exc:
            raise RegistrarPermanentError(str(exc)) from exc
        except (MoySkladConnectionError, ExternalSideEffectInProgressError) as exc:
            raise RegistrarTransientError(str(exc)) from exc
