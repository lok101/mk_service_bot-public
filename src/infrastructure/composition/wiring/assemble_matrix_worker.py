from __future__ import annotations

from beartype import beartype

from src.application.snack_loading import DomainMatrixStockProvider
from src.config.settings import Settings, get_settings, validate_matrix_worker_settings
from src.infrastructure.composition.factories import build_snack_machine_stock_store
from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer
from src.infrastructure.composition.wiring.wire_matrix_worker import wire_matrix_worker
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence


@beartype
def assemble_matrix_worker(settings: Settings | None = None) -> MatrixWorkerContainer:
    resolved = settings or get_settings()
    validate_matrix_worker_settings(resolved)
    persistence = wire_persistence(resolved)
    stock_store = build_snack_machine_stock_store(
        resolved,
        client=persistence.mongo_client,
    )
    stock_provider = DomainMatrixStockProvider(store=stock_store)
    return wire_matrix_worker(
        resolved,
        persistence=persistence,
        stock_provider=stock_provider,
    )
