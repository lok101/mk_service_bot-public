from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.snack_loading.ports import (
    KitMatrixDeployMapStore,
    ResolvedSaleForReplay,
)

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class DeployMappedSnackSalesAfter:
    """Map kit sales rows to replay DTOs via deploy-map logical matrix names."""

    sales_store: MachineSalesStore
    deploy_map: KitMatrixDeployMapStore

    @beartype
    def query(
        self,
        machine_code: str,
        after: datetime,
    ) -> Sequence[ResolvedSaleForReplay]:
        rows: list[ResolvedSaleForReplay] = []
        for sale in self.sales_store.find_after_by_machine_code(machine_code, after=after):
            if sale.resolve_status != "resolved":
                continue
            if sale.kit_matrix_id is None or sale.kit_line_number is None:
                continue
            mapped = self.deploy_map.get(sale.kit_matrix_id)
            if mapped is None or mapped.machine_code != machine_code:
                _logger.warning(
                    "snack_inventory_replay_deploy_map_skip",
                    extra={
                        "source_id": sale.source_id,
                        "machine_code": machine_code,
                        "kit_matrix_id": sale.kit_matrix_id,
                        "mapped_machine_code": (None if mapped is None else mapped.machine_code),
                    },
                )
                continue
            rows.append(
                ResolvedSaleForReplay(
                    source_id=sale.source_id,
                    logical_matrix_name=mapped.logical_matrix_name,
                    line_number=sale.kit_line_number,
                    product_code=sale.product_code,
                    quantity=sale.quantity,
                    occurred_at=sale.occurred_at,
                    resolve_status=sale.resolve_status,
                ),
            )
        return tuple(rows)
