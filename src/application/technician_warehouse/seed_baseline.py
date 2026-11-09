from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from beartype import beartype

from src.application.technician_warehouse.errors import (
    SeedWarehouseBaselineError,
    SeedWarehouseBaselinePartialWriteError,
)
from src.application.technician_warehouse.ports import (
    SeedProductCatalog,
    TechnicianWarehouseCommandExecutor,
    TechnicianWarehouseEventStore,
)
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
)

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class SeedDryRunReport:
    ok_technician_ids: tuple[str, ...]
    issues: tuple[str, ...]


@beartype
@dataclass(frozen=True, slots=True)
class SeedConfirmResult:
    seeded_technician_ids: tuple[str, ...]


@beartype
@dataclass(frozen=True, slots=True)
class _ValidatedTechnicianSeed:
    technician_id: str
    counted_at: datetime
    stocks_by_code: dict[str, Decimal]


@beartype
@dataclass(frozen=True, slots=True)
class SeedTechnicianWarehouseBaseline:
    executor: TechnicianWarehouseCommandExecutor
    event_store: TechnicianWarehouseEventStore
    catalog: SeedProductCatalog

    @beartype
    def write_template(
        self,
        *,
        technician_ids: tuple[str, ...],
        output_path: Path,
    ) -> None:
        code_to_name = self.catalog.code_to_name()
        stocks = [
            {
                "product_code": code,
                "product_name": code_to_name[code],
                "stock": None,
            }
            for code in sorted(code_to_name)
        ]
        payload = {
            "technicians": [
                {
                    "technician_id": technician_id,
                    "counted_at": None,
                    "stocks": stocks,
                }
                for technician_id in technician_ids
            ]
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8-sig",
        )

    @beartype
    def dry_run(self, file_path: Path) -> SeedDryRunReport:
        validated = self._validate_file(file_path)
        return SeedDryRunReport(
            ok_technician_ids=tuple(item.technician_id for item in validated),
            issues=(),
        )

    @beartype
    def confirm(self, file_path: Path) -> SeedConfirmResult:
        validated = self._validate_file(file_path)
        written: list[str] = []
        for item in validated:
            try:
                self._write_one(item)
            except SeedWarehouseBaselineError:
                raise
            except Exception as exc:
                raise SeedWarehouseBaselinePartialWriteError(
                    written_technician_ids=tuple(written),
                    cause=exc,
                ) from exc
            written.append(item.technician_id)
        return SeedConfirmResult(seeded_technician_ids=tuple(written))

    @beartype
    def _write_one(self, item: _ValidatedTechnicianSeed) -> None:
        seed_id = f"seed:{item.technician_id}:{item.counted_at.isoformat()}"
        self.executor.execute(
            TechnicianId(item.technician_id),
            lambda wh: wh.count_inventory(
                inventory_id=seed_id,
                form_token=seed_id,
                counted_at=item.counted_at,
                actual_by_sku=item.stocks_by_code,
                baseline=True,
            ),
        )
        _logger.info(
            "seeded warehouse baseline technician_id=%s inventory_id=%s counted_at=%s sku_count=%s",
            item.technician_id,
            seed_id,
            item.counted_at.isoformat(),
            len(item.stocks_by_code),
        )

    @beartype
    def _validate_file(self, file_path: Path) -> tuple[_ValidatedTechnicianSeed, ...]:
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SeedWarehouseBaselineError(f"invalid seed file: {exc}") from exc

        if not isinstance(raw, dict):
            raise SeedWarehouseBaselineError("seed file root must be an object")

        technicians = raw.get("technicians")
        if not isinstance(technicians, list) or not technicians:
            raise SeedWarehouseBaselineError("technicians must be a non-empty array")

        catalog_codes = set(self.catalog.code_to_name())
        validated: list[_ValidatedTechnicianSeed] = []
        for index, entry in enumerate(technicians):
            validated.append(self._validate_technician_entry(entry, index, catalog_codes))
        return tuple(validated)

    @beartype
    def _validate_technician_entry(
        self,
        entry: Any,
        index: int,
        catalog_codes: set[str],
    ) -> _ValidatedTechnicianSeed:
        if not isinstance(entry, dict):
            raise SeedWarehouseBaselineError(f"technician[{index}] must be an object")

        technician_id = entry.get("technician_id")
        if not isinstance(technician_id, str) or not technician_id:
            raise SeedWarehouseBaselineError(f"technician[{index}]: technician_id required")

        counted_at = self._parse_counted_at(entry.get("counted_at"), technician_id)
        stocks = entry.get("stocks")
        if not isinstance(stocks, list):
            raise SeedWarehouseBaselineError(f"technician {technician_id}: stocks must be an array")

        stocks_by_code = self._parse_stocks(stocks, technician_id=technician_id)
        file_codes = set(stocks_by_code)

        missing = sorted(catalog_codes - file_codes)
        if missing:
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: missing catalog SKU(s): {', '.join(missing)}"
            )

        unknown = sorted(file_codes - catalog_codes)
        if unknown:
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: unknown product_code(s): {', '.join(unknown)}"
            )

        self._validate_stream_guards(
            technician_id=technician_id,
            counted_at=counted_at,
        )

        return _ValidatedTechnicianSeed(
            technician_id=technician_id,
            counted_at=counted_at,
            stocks_by_code=stocks_by_code,
        )

    @beartype
    def _validate_stream_guards(self, *, technician_id: str, counted_at: datetime) -> None:
        events = self.event_store.get_events_for_technician(TechnicianId(technician_id))
        if any(isinstance(event, TechnicianWarehouseInventoryCounted) for event in events):
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: inventory already exists in warehouse stream"
            )

        voided_ids = {
            event.external_document_id
            for event in events
            if isinstance(event, TechnicianWarehouseTransferVoided)
        }
        issues: list[str] = []
        for event in events:
            if isinstance(event, TechnicianWarehouseLoadingObserved):
                if event.submitted_at <= counted_at:
                    issues.append(
                        f"loading source_event_id={event.source_event_id} "
                        f"submitted_at={event.submitted_at.isoformat()} <= counted_at"
                    )
            elif (
                isinstance(event, TechnicianWarehouseTransferObserved)
                and event.moment <= counted_at
                and event.external_document_id not in voided_ids
            ):
                issues.append(
                    f"transfer external_document_id={event.external_document_id} "
                    f"moment={event.moment.isoformat()} <= counted_at"
                )
        if issues:
            joined = "; ".join(issues)
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: stream violations before/at counted_at: {joined}"
            )

    @beartype
    def _parse_counted_at(self, raw: Any, technician_id: str) -> datetime:
        if raw is None:
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: counted_at is required (timezone-aware ISO 8601)"
            )
        if not isinstance(raw, str):
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: counted_at must be an ISO 8601 string"
            )
        try:
            counted_at = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: counted_at is not valid ISO 8601: {raw!r}"
            ) from exc
        if counted_at.tzinfo is None:
            raise SeedWarehouseBaselineError(
                f"technician {technician_id}: counted_at must be timezone-aware (got naive)"
            )
        return counted_at

    @beartype
    def _parse_stocks(
        self,
        stocks: list[Any],
        *,
        technician_id: str,
    ) -> dict[str, Decimal]:
        stocks_by_code: dict[str, Decimal] = {}
        for index, item in enumerate(stocks):
            if not isinstance(item, dict):
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: stocks[{index}] must be an object"
                )
            product_code = item.get("product_code")
            if not isinstance(product_code, str) or not product_code:
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: stocks[{index}]: product_code required"
                )
            if product_code in stocks_by_code:
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: duplicate product_code: {product_code}"
                )
            if "stock" not in item:
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: stock missing for product_code={product_code}"
                )
            stock_raw = item["stock"]
            if stock_raw is None:
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: stock is null for product_code={product_code}"
                )
            try:
                quantity = Decimal(str(stock_raw))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: stock is not a number for "
                    f"product_code={product_code}: {stock_raw!r}"
                ) from exc
            if quantity < 0:
                raise SeedWarehouseBaselineError(
                    f"technician {technician_id}: stock must be >= 0 for "
                    f"product_code={product_code} (got {quantity})"
                )
            stocks_by_code[product_code] = quantity
        return stocks_by_code
