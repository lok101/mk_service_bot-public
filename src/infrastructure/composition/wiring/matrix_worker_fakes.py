from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.matrix_automation import MatrixDeployJob
from src.infrastructure.moysklad.purchase_prices.models import PurchaseAttributesBatchResult


@beartype
@dataclass(slots=True)
class _SystemUtcClock:
    def now_utc_iso(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@beartype
class _InMemoryWorkerStatusRepository:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []
        self.terminal_jobs: list[MatrixDeployJob] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))

    def record_terminal_job(self, job: MatrixDeployJob) -> None:
        self.terminal_jobs.append(job)


@beartype
@dataclass(slots=True)
class _JobLoggerAdapter:
    _logger: logging.Logger

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.exception(message, *args, exc_info=True)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        del kwargs
        self._logger.warning(message, *args)

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        del kwargs
        self._logger.error(message, *args)


@beartype
class _EmptyPurchaseClient:
    def fetch_purchase_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesBatchResult:
        return PurchaseAttributesBatchResult(attributes={}, cards_found=0)


@beartype
class NoOpMatrixWorkerStatusRepository:
    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        return None

    def record_terminal_job(self, job: MatrixDeployJob) -> None:
        return None
