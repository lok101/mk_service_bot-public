from __future__ import annotations

from src.domain.snack_loading.aggregate import SnackMachineStock
from src.domain.snack_loading.errors import SnackStockConcurrencyError
from src.domain.snack_loading.events import (
    CellKey,
    SnackInventoryAccepted,
    SnackLoadingApplied,
    SnackSaleDeducted,
    SnackStockAnomalyRecorded,
    SnackStockEvent,
)

__all__ = [
    "CellKey",
    "SnackInventoryAccepted",
    "SnackLoadingApplied",
    "SnackMachineStock",
    "SnackSaleDeducted",
    "SnackStockAnomalyRecorded",
    "SnackStockConcurrencyError",
    "SnackStockEvent",
]
