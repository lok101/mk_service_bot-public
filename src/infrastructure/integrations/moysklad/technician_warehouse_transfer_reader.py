from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from beartype import beartype

from src.application.technician_warehouse import TechnicianWarehouseImportBlocked
from src.application.technician_warehouse.ports import (
    ExternalWarehouseMove,
    ExternalWarehouseMoveLine,
    ReadMovesResult,
)
from src.domain.technician_warehouse.errors import MoySkladUnavailable
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladError,
    MoySkladValidationError,
)
from src.infrastructure.integrations.moysklad.expand import META_ONLY_FALLBACK_CAP
from src.infrastructure.integrations.moysklad.quantities import parse_moysklad_quantity

_LOGGER = logging.getLogger(__name__)
_SKIPPED_UNRESOLVED_SAMPLE_LIMIT = 5


@beartype
def _is_expanded_store(store: Mapping[str, Any]) -> bool:
    return any(key != "meta" for key in store)


@beartype
def _move_applicable(row: Mapping[str, Any]) -> bool:
    """MS ``applicable``: only explicit True is posted; missing defaults to True."""
    if "applicable" not in row:
        return True
    return row["applicable"] is True


@beartype
def _log_store_resolve_counters(
    *,
    stores_expanded: int,
    stores_meta_only: int,
    store_code_fallback_gets: int,
) -> None:
    _LOGGER.info(
        "technician_warehouse_ms_store_resolve "
        "stores_expanded=%s stores_meta_only=%s store_code_fallback_gets=%s",
        stores_expanded,
        stores_meta_only,
        store_code_fallback_gets,
    )


@beartype
def _parse_moment(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value)
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)


@beartype
def _store_id_from_href(href: object) -> UUID:
    text = str(href)
    suffix = text.rsplit("/", maxsplit=1)[-1]
    return UUID(suffix)


@beartype
def _positions_rows_from_move(
    row: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], bool] | None:
    """Extract expanded position rows.

    Returns ``(rows, truncated)`` where ``truncated`` is True when
    ``positions.meta.size`` exceeds the expanded page (need paginated GET).
    ``None`` when expand missing/meta-only.
    """
    positions = row.get("positions")
    if not isinstance(positions, Mapping):
        return None
    rows = positions.get("rows")
    if not isinstance(rows, list):
        return None
    collected = [item for item in rows if isinstance(item, Mapping)]
    meta = positions.get("meta")
    size: int | None = None
    if isinstance(meta, Mapping):
        raw_size = meta.get("size")
        if isinstance(raw_size, int):
            size = raw_size
        elif isinstance(raw_size, str) and raw_size.isdigit():
            size = int(raw_size)
    truncated = size is not None and size > len(collected)
    return collected, truncated


@beartype
@dataclass(frozen=True, slots=True)
class _TechRelevantMove:
    move_id: str
    row: Mapping[str, Any]
    source_code: str
    target_code: str


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladTechnicianWarehouseTransferReader:
    client: MoySkladClientPort

    @beartype
    async def ensure_supply_store_codes_exist(self, codes: tuple[str, ...]) -> None:
        # One filter GET per env code (usually small). Not the lookback N+1 store
        # bug; still avoid inventing per-id GETs here — see moysklad.expand.
        for code in codes:
            try:
                await self.client.get_store_id_by_code(code)
            except MoySkladValidationError as error:
                message = str(error)
                if "не найден" in message or "not found" in message.lower():
                    raise TechnicianWarehouseImportBlocked(
                        f"TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES: store code {code!r} "
                        f"not found in MoySklad ({message})",
                    ) from error
                raise MoySkladUnavailable(message) from error
            except MoySkladError as error:
                raise MoySkladUnavailable(str(error)) from error

    @beartype
    async def read_moves(
        self,
        *,
        technician_store_code: str,
        moment_from: datetime,
        moment_to: datetime,
    ) -> ReadMovesResult:
        try:
            rows = await self.client.get_move_list(
                moment_from=moment_from,
                moment_to=moment_to,
            )
        except MoySkladError as error:
            raise MoySkladUnavailable(str(error)) from error

        store_codes = await self._resolve_store_codes(rows)
        candidates: list[_TechRelevantMove] = []
        skipped_unresolved = 0
        skipped_sample: list[str] = []
        for row in rows:
            candidate, skip_reason = self._classify_move(
                row,
                store_codes=store_codes,
                technician_store_code=technician_store_code,
            )
            if skip_reason == "unresolved":
                skipped_unresolved += 1
                move_id = str(row.get("id", ""))
                if move_id and len(skipped_sample) < _SKIPPED_UNRESOLVED_SAMPLE_LIMIT:
                    skipped_sample.append(move_id)
                continue
            if candidate is not None:
                candidates.append(candidate)
        if skipped_sample:
            _LOGGER.info(
                "technician_warehouse_ms_moves_skipped_unresolved count=%s sample_move_ids=%s",
                skipped_unresolved,
                skipped_sample,
            )
        if not candidates:
            return ReadMovesResult(moves=(), skipped_unresolved=skipped_unresolved)

        positions_by_id = await self._load_positions_batched(
            tuple(candidate.move_id for candidate in candidates),
        )
        moves: list[ExternalWarehouseMove] = []
        for candidate in candidates:
            positions = positions_by_id.get(candidate.move_id)
            if positions is None:
                raise MoySkladUnavailable(
                    f"Move {candidate.move_id} positions expand missing after batch fetch",
                )
            lines = tuple(self._normalize_line(position) for position in positions)
            moves.append(
                ExternalWarehouseMove(
                    document_id=candidate.move_id,
                    source_store_code=candidate.source_code,
                    target_store_code=candidate.target_code,
                    moment=_parse_moment(candidate.row["moment"]),
                    updated_at=_parse_moment(candidate.row["updated"]),
                    lines=lines,
                    applicable=_move_applicable(candidate.row),
                ),
            )
        return ReadMovesResult(moves=tuple(moves), skipped_unresolved=skipped_unresolved)

    @beartype
    async def _resolve_store_codes(
        self,
        rows: list[Mapping[str, Any]],
    ) -> dict[UUID, str]:
        """Map store UUID → code for moves in the window.

        Preferred source: expanded ``sourceStore`` / ``targetStore`` on the move
        list (``expand.MOVE_LIST_STORE_EXPAND``). Per-id
        ``get_store_code_by_id`` is a last resort for meta-only refs only and
        risks HTTP 429 — see ``src.infrastructure.integrations.moysklad.expand``.
        """
        occurrences: dict[UUID, list[Mapping[str, Any]]] = {}
        for row in rows:
            for key in ("sourceStore", "targetStore"):
                store = row.get(key)
                if not isinstance(store, Mapping):
                    continue
                meta = store.get("meta")
                if not isinstance(meta, Mapping):
                    continue
                href = meta.get("href")
                if href is None:
                    continue
                store_id = _store_id_from_href(href)
                occurrences.setdefault(store_id, []).append(store)

        if not occurrences:
            _log_store_resolve_counters(
                stores_expanded=0,
                stores_meta_only=0,
                store_code_fallback_gets=0,
            )
            return {}

        expanded_ids: set[UUID] = set()
        meta_only_ids: set[UUID] = set()
        for store_id, stores in occurrences.items():
            if any(_is_expanded_store(store) for store in stores):
                expanded_ids.add(store_id)
            else:
                meta_only_ids.add(store_id)

        stores_expanded = len(expanded_ids)
        stores_meta_only = len(meta_only_ids)

        if stores_expanded == 0:
            _log_store_resolve_counters(
                stores_expanded=0,
                stores_meta_only=stores_meta_only,
                store_code_fallback_gets=0,
            )
            raise MoySkladUnavailable(
                f"move list store expand missing "
                f"(unique_store_ids={len(occurrences)} expanded_ids=0)",
            )

        if stores_meta_only > META_ONLY_FALLBACK_CAP:
            _log_store_resolve_counters(
                stores_expanded=stores_expanded,
                stores_meta_only=stores_meta_only,
                store_code_fallback_gets=0,
            )
            raise MoySkladUnavailable(
                f"excessive meta-only store refs "
                f"(meta_only={stores_meta_only} cap={META_ONLY_FALLBACK_CAP})",
            )

        resolved: dict[UUID, str] = {}
        for store_id in expanded_ids:
            codes: list[str] = []
            for store in occurrences[store_id]:
                if not _is_expanded_store(store):
                    continue
                raw = store.get("code")
                if raw is None:
                    continue
                stripped = str(raw).strip()
                if stripped:
                    codes.append(stripped)
            unique_codes = sorted(set(codes))
            if len(unique_codes) >= 2:
                _log_store_resolve_counters(
                    stores_expanded=stores_expanded,
                    stores_meta_only=stores_meta_only,
                    store_code_fallback_gets=0,
                )
                raise MoySkladUnavailable(
                    f"Conflicting store codes for {store_id}: "
                    f"{unique_codes[0]!r} vs {unique_codes[1]!r}",
                )
            if len(unique_codes) == 1:
                resolved[store_id] = unique_codes[0]

        store_code_fallback_gets = 0
        for store_id in meta_only_ids:
            try:
                code = await self.client.get_store_code_by_id(store_id)
            except MoySkladValidationError as error:
                if "has no code" in str(error):
                    store_code_fallback_gets += 1
                    continue
                raise MoySkladUnavailable(str(error)) from error
            except MoySkladError as error:
                raise MoySkladUnavailable(str(error)) from error
            store_code_fallback_gets += 1
            stripped = code.strip()
            if not stripped:
                continue
            resolved[store_id] = stripped

        _log_store_resolve_counters(
            stores_expanded=stores_expanded,
            stores_meta_only=stores_meta_only,
            store_code_fallback_gets=store_code_fallback_gets,
        )
        return resolved

    @beartype
    def _classify_move(
        self,
        row: Mapping[str, Any],
        *,
        store_codes: dict[UUID, str],
        technician_store_code: str,
    ) -> tuple[_TechRelevantMove | None, Literal["unresolved"] | None]:
        source_code = self._store_code(row.get("sourceStore"), store_codes=store_codes)
        target_code = self._store_code(row.get("targetStore"), store_codes=store_codes)
        if source_code is None or target_code is None:
            return None, "unresolved"
        if technician_store_code not in {source_code, target_code}:
            return None, None
        return (
            _TechRelevantMove(
                move_id=str(row["id"]),
                row=row,
                source_code=source_code,
                target_code=target_code,
            ),
            None,
        )

    @beartype
    async def _load_positions_batched(
        self,
        move_ids: tuple[str, ...],
    ) -> dict[str, list[Mapping[str, Any]]]:
        try:
            batched_rows = await self.client.get_moves_by_ids(move_ids=move_ids)
        except MoySkladError as error:
            raise MoySkladUnavailable(str(error)) from error
        positions_by_id: dict[str, list[Mapping[str, Any]]] = {}
        for row in batched_rows:
            move_id = str(row.get("id", ""))
            if not move_id:
                continue
            extracted = _positions_rows_from_move(row)
            if extracted is None:
                raise MoySkladUnavailable(
                    f"Move {move_id} positions expand dead or meta-only",
                )
            positions, truncated = extracted
            if truncated:
                try:
                    positions = await self._load_move_positions_paginated(move_id)
                except MoySkladError as error:
                    raise MoySkladUnavailable(str(error)) from error
            positions_by_id[move_id] = positions
        return positions_by_id

    @beartype
    async def _load_move_positions_paginated(
        self,
        move_id: str,
    ) -> list[Mapping[str, Any]]:
        """Fallback when expand page truncates positions (meta.size > len(rows))."""
        limit = 100
        offset = 0
        collected: list[Mapping[str, Any]] = []
        while True:
            page = await self.client.get_move_positions(
                move_id=move_id,
                limit=limit,
                offset=offset,
            )
            collected.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return collected

    @beartype
    def _store_code(
        self,
        store: object,
        *,
        store_codes: dict[UUID, str],
    ) -> str | None:
        if not isinstance(store, Mapping):
            raise ValueError("Move store reference is missing.")
        meta = store.get("meta")
        if not isinstance(meta, Mapping):
            raise ValueError("Move store meta is missing.")
        href = meta.get("href")
        if href is None:
            raise ValueError("Move store href is missing.")
        store_id = _store_id_from_href(href)
        return store_codes.get(store_id)

    @beartype
    def _normalize_line(self, position: Mapping[str, Any]) -> ExternalWarehouseMoveLine:
        assortment = position["assortment"]
        if not isinstance(assortment, Mapping):
            raise ValueError("Move position assortment is missing.")
        code = str(assortment["code"])
        name = str(assortment.get("name", code))
        quantity = parse_moysklad_quantity(position["quantity"])
        return ExternalWarehouseMoveLine(
            product_code=code,
            product_name=name,
            quantity=quantity,
        )
