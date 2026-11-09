from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from beartype import beartype

from src.application.technician_warehouse.errors import TechnicianWarehouseImportBlocked
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.ports import (
    BorderProductGate,
    CatalogBaseQuantityResolver,
    ExternalWarehouseMove,
    ImportedTransferRef,
    TechnicianWarehouseTransferReader,
    UnmatchedMsProduct,
)
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_warehouse.errors import FinalizedTransferChangedError
from src.domain.technician_warehouse.events import TechnicianWarehouseTransferObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection

_LOGGER = logging.getLogger(__name__)
_UNPOSTED_MS_MOVES_SAMPLE_LIMIT = 5
_UNREGISTERED_BORDER_SAMPLE_LIMIT = 5


@beartype
def format_unposted_ms_moves_blocker(*, document_ids: tuple[str, ...]) -> str:
    """Stable reconcile blocker text for unposted supply↔technician MS moves."""
    ordered = tuple(sorted(document_ids))
    sample = ordered[:_UNPOSTED_MS_MOVES_SAMPLE_LIMIT]
    return (
        "unposted MS supply↔technician moves block reconcile "
        f"(count={len(ordered)} sample={','.join(sample)})"
    )


@beartype
def format_unregistered_border_blocker(
    *,
    products: tuple[tuple[str, str], ...],
) -> str:
    """Blocker / exception text for unregistered MS codes on the warehouse border."""
    ordered = tuple(sorted(products, key=lambda item: item[0]))
    sample = ordered[:_UNREGISTERED_BORDER_SAMPLE_LIMIT]
    lines: list[str] = []
    for code, name in sample:
        trimmed = name.strip()
        lines.append(code if not trimmed else f"{code} — {trimmed}")
    body = "; ".join(lines)
    remaining = len(ordered) - len(sample)
    suffix = f"; и ещё {remaining}" if remaining > 0 else ""
    return (
        f"unregistered MS border products block import (count={len(ordered)} sample={body}{suffix})"
    )


@beartype
@dataclass(frozen=True, slots=True)
class IgnoredFinalizedTransfer:
    external_document_id: str
    kind: Literal["changed", "missing"]
    session_id: str = ""


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseImportResult:
    imported: int
    updated: int
    voided: int
    ignored: int
    skipped_unresolved: int
    truncated_non_domain: int
    transfer_refs: tuple[ImportedTransferRef, ...]
    unmatched_products: tuple[UnmatchedMsProduct, ...]
    ignored_finalized_transfers: tuple[IgnoredFinalizedTransfer, ...] = ()

    @beartype
    def to_cli_dict(self) -> dict[str, object]:
        return {
            "imported": self.imported,
            "updated": self.updated,
            "voided": self.voided,
            "ignored": self.ignored,
            "skipped_unresolved": self.skipped_unresolved,
            "truncated_non_domain": self.truncated_non_domain,
            "unmatched_products": [
                {
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "external_document_id": product.external_document_id,
                }
                for product in self.unmatched_products
            ],
            "transfer_refs": [
                {
                    "external_document_id": ref.external_document_id,
                    "content_hash": ref.content_hash,
                }
                for ref in self.transfer_refs
            ],
            "ignored_finalized_transfers": [
                {
                    "external_document_id": item.external_document_id,
                    "kind": item.kind,
                    "session_id": item.session_id,
                }
                for item in self.ignored_finalized_transfers
            ],
        }


@beartype
@dataclass(slots=True)
class ImportTechnicianWarehouseTransfers:
    reader: TechnicianWarehouseTransferReader
    catalog_base_quantity_resolver: CatalogBaseQuantityResolver
    executor: TechnicianWarehouseExecutor
    supply_store_codes: tuple[str, ...]
    lookback_days: int
    border_gate: BorderProductGate | None = None

    @beartype
    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult:
        if not self.supply_store_codes:
            raise TechnicianWarehouseImportBlocked(
                "TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES is required for import",
            )

        await self.reader.ensure_supply_store_codes_exist(self.supply_store_codes)

        window_from = self._window_from(technician_id, anchor_at)
        _LOGGER.info(
            "technician_warehouse_ms_import_started technician_id=%s window_from=%s anchor_at=%s",
            technician_id.value,
            window_from.isoformat(),
            anchor_at.isoformat(),
        )
        read_result = await self.reader.read_moves(
            technician_store_code=technician_id.value,
            moment_from=window_from,
            moment_to=anchor_at,
        )
        self._raise_if_unposted_supply_tech_moves(
            read_result.moves,
            technician_code=technician_id.value,
        )
        in_window = tuple(
            move for move in read_result.moves if window_from <= move.moment <= anchor_at
        )
        self._raise_if_unregistered_border(
            in_window,
            technician_code=technician_id.value,
        )
        result = self._normalize_compare_and_append(
            technician_id,
            in_window,
            window_from=window_from,
            anchor_at=anchor_at,
            skipped_unresolved=read_result.skipped_unresolved,
        )
        _LOGGER.info(
            "technician_warehouse_ms_import_completed technician_id=%s imported=%s updated=%s "
            "voided=%s ignored=%s skipped_unresolved=%s truncated_non_domain=%s unmatched=%s",
            technician_id.value,
            result.imported,
            result.updated,
            result.voided,
            result.ignored,
            result.skipped_unresolved,
            result.truncated_non_domain,
            len(result.unmatched_products),
        )
        return result

    @beartype
    def _window_from(self, technician_id: TechnicianId, anchor_at: datetime) -> datetime:
        warehouse = self.executor.repository.get(technician_id)
        previous_inventory_at = warehouse.latest_inventory_counted_at_at_or_before(anchor_at)
        if previous_inventory_at is not None:
            return previous_inventory_at - timedelta(days=self.lookback_days)
        return anchor_at - timedelta(days=self.lookback_days)

    @beartype
    def _raise_if_unposted_supply_tech_moves(
        self,
        moves: tuple[ExternalWarehouseMove, ...],
        *,
        technician_code: str,
    ) -> None:
        supply_codes = set(self.supply_store_codes)
        unposted_ids = tuple(
            move.document_id
            for move in moves
            if (not move.applicable)
            and self._classify_move(
                move,
                technician_code=technician_code,
                supply_codes=supply_codes,
            )
            is not None
        )
        if unposted_ids:
            raise TechnicianWarehouseImportBlocked(
                format_unposted_ms_moves_blocker(document_ids=unposted_ids),
            )

    @beartype
    def _normalize_compare_and_append(
        self,
        technician_id: TechnicianId,
        moves: tuple[ExternalWarehouseMove, ...],
        *,
        window_from: datetime,
        anchor_at: datetime,
        skipped_unresolved: int,
    ) -> TechnicianWarehouseImportResult:
        imported = 0
        updated = 0
        voided = 0
        ignored = 0
        truncated_non_domain = 0
        transfer_refs: list[ImportedTransferRef] = []
        ignored_finalized: list[IgnoredFinalizedTransfer] = []
        seen_document_ids: set[str] = set()
        supply_codes = set(self.supply_store_codes)
        technician_code = technician_id.value

        for move in moves:
            direction = self._classify_move(
                move,
                technician_code=technician_code,
                supply_codes=supply_codes,
            )
            if direction is None:
                ignored += 1
                continue

            resolved_lines, truncated = self._resolve_lines(move)
            if resolved_lines is None:
                continue
            truncated_non_domain += truncated
            # Truncate-all still observes empty lines so reimport can fill after catalog add.
            seen_document_ids.add(move.document_id)

            content_hash = _transfer_content_hash(direction, resolved_lines)
            event = TechnicianWarehouseTransferObserved(
                event_id=EventId(str(uuid.uuid4())),
                technician_id=technician_id,
                occurred_at=datetime.now(tz=UTC),
                external_document_id=move.document_id,
                moment=move.moment,
                updated_at=move.updated_at,
                observed_at=anchor_at,
                content_hash=content_hash,
                direction=direction,
                lines=resolved_lines,
            )
            pending_ref = ImportedTransferRef(
                external_document_id=move.document_id,
                content_hash=content_hash,
            )
            drift_kind: Literal["changed"] | None = None

            def observe_command(
                warehouse: object,
                *,
                observed_event: TechnicianWarehouseTransferObserved = event,
                document_id: str = move.document_id,
            ) -> None:
                nonlocal imported, updated, drift_kind
                from src.domain.technician_warehouse import TechnicianWarehouse

                assert isinstance(warehouse, TechnicianWarehouse)
                if warehouse.is_transfer_finalized(document_id):
                    try:
                        warehouse.observe_transfer(observed_event)
                    except FinalizedTransferChangedError:
                        drift_kind = "changed"
                        _LOGGER.warning(
                            "technician_warehouse_finalized_transfer_ignored "
                            "document_id=%s kind=changed",
                            document_id,
                        )
                    return
                had_transfer = document_id in warehouse.observed_transfer_document_ids()
                observed = warehouse.observe_transfer(observed_event)
                if observed is None:
                    return
                if had_transfer:
                    updated += 1
                else:
                    imported += 1

            self.executor.execute(technician_id, observe_command)
            if drift_kind is not None:
                ignored += 1
                ignored_finalized.append(
                    IgnoredFinalizedTransfer(
                        external_document_id=move.document_id,
                        kind=drift_kind,
                    ),
                )
                continue
            transfer_refs.append(pending_ref)

        warehouse = self.executor.repository.get(technician_id)
        for document_id in warehouse.transfer_document_ids_in_moment_window(
            moment_from=window_from,
            moment_to=anchor_at,
        ):
            if document_id in seen_document_ids:
                continue

            missing_finalized = False

            def void_command(
                warehouse_state: object,
                *,
                external_document_id: str = document_id,
            ) -> None:
                nonlocal voided, missing_finalized
                from src.domain.technician_warehouse import TechnicianWarehouse

                assert isinstance(warehouse_state, TechnicianWarehouse)
                try:
                    voided_event = warehouse_state.void_transfer(
                        external_document_id=external_document_id,
                        observed_at=anchor_at,
                    )
                except FinalizedTransferChangedError:
                    missing_finalized = True
                    _LOGGER.warning(
                        "technician_warehouse_finalized_transfer_ignored "
                        "document_id=%s kind=missing",
                        external_document_id,
                    )
                    return
                if voided_event is not None:
                    voided += 1

            self.executor.execute(technician_id, void_command)
            if missing_finalized:
                ignored += 1
                ignored_finalized.append(
                    IgnoredFinalizedTransfer(
                        external_document_id=document_id,
                        kind="missing",
                    ),
                )

        return TechnicianWarehouseImportResult(
            imported=imported,
            updated=updated,
            voided=voided,
            ignored=ignored,
            skipped_unresolved=skipped_unresolved,
            truncated_non_domain=truncated_non_domain,
            transfer_refs=tuple(transfer_refs),
            unmatched_products=(),
            ignored_finalized_transfers=tuple(ignored_finalized),
        )

    @beartype
    def _classify_move(
        self,
        move: ExternalWarehouseMove,
        *,
        technician_code: str,
        supply_codes: set[str],
    ) -> TransferDirection | None:
        if move.source_store_code in supply_codes and move.target_store_code == technician_code:
            return TransferDirection.SUPPLY_IN
        if move.source_store_code == technician_code and move.target_store_code in supply_codes:
            return TransferDirection.SUPPLY_RETURN
        return None

    @beartype
    def _raise_if_unregistered_border(
        self,
        moves: tuple[ExternalWarehouseMove, ...],
        *,
        technician_code: str,
    ) -> None:
        if self.border_gate is None:
            return
        supply_codes = set(self.supply_store_codes)
        codes: list[str] = []
        names_by_code: dict[str, str] = {}
        for move in moves:
            if (
                self._classify_move(
                    move,
                    technician_code=technician_code,
                    supply_codes=supply_codes,
                )
                is None
            ):
                continue
            for line in move.lines:
                codes.append(line.product_code)
                trimmed_code = line.product_code.strip()
                if not trimmed_code:
                    continue
                existing_name = names_by_code.get(trimmed_code, "")
                if trimmed_code not in names_by_code or (
                    not existing_name.strip() and line.product_name.strip()
                ):
                    names_by_code[trimmed_code] = line.product_name
        unregistered = self.border_gate.unregistered_among(tuple(codes))
        if unregistered:
            self.border_gate.note_unregistered(unregistered)
            products = tuple((code, names_by_code.get(code, "")) for code in unregistered)
            raise TechnicianWarehouseImportBlocked(
                format_unregistered_border_blocker(products=products),
                technician_id=technician_code,
                unregistered_products=products,
            )

    @beartype
    def _resolve_lines(
        self,
        move: ExternalWarehouseMove,
    ) -> tuple[tuple[TechnicianWarehouseLine, ...] | None, int]:
        """None lines = skip document (invalid empty product_code). int = truncated count."""
        if any(not line.product_code.strip() for line in move.lines):
            _LOGGER.warning(
                "technician_warehouse_ms_invalid_product_code document_id=%s",
                move.document_id,
            )
            return None, 0

        lines: list[TechnicianWarehouseLine] = []
        truncated = 0
        for line in move.lines:
            if self.border_gate is not None and self.border_gate.is_ignored(line.product_code):
                truncated += 1
                _LOGGER.info(
                    "technician_warehouse_ms_product_ignored document_id=%s code=%s",
                    move.document_id,
                    line.product_code,
                )
                continue
            resolved = self.catalog_base_quantity_resolver.try_resolve_line(
                product_code=line.product_code,
                moysklad_quantity=line.quantity,
            )
            if resolved is None:
                truncated += 1
                _LOGGER.info(
                    "technician_warehouse_ms_product_truncated document_id=%s code=%s",
                    move.document_id,
                    line.product_code,
                )
                continue
            sku, quantity_base = resolved
            lines.append(TechnicianWarehouseLine(sku=sku, quantity_base=quantity_base))
        return tuple(lines), truncated


@beartype
def _transfer_content_hash(
    direction: TransferDirection,
    lines: tuple[TechnicianWarehouseLine, ...],
) -> str:
    parts = [direction.value]
    for line in sorted(lines, key=lambda item: item.sku):
        parts.append(f"{line.sku}:{line.quantity_base}")
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode()).hexdigest()
