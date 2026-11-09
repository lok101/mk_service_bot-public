from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.technician_warehouse import IgnoredFinalizedTransfer

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_MESSAGE_SOFT_LIMIT = 3500


@runtime_checkable
class FinalizedTransferDriftOpsAlerter(Protocol):
    def notify_drift(
        self,
        *,
        technician_id: str,
        items: tuple[IgnoredFinalizedTransfer, ...],
    ) -> None: ...


@beartype
def format_finalized_transfer_drift_ops_message(
    *,
    technician_id: str,
    items: tuple[IgnoredFinalizedTransfer, ...],
) -> str:
    ordered = tuple(sorted(items, key=lambda item: item.external_document_id))
    lines = [
        "Изменено учтённое перемещение МС (закрытая сверка)",
        f"Техник: {technician_id}",
        f"Перемещений: {len(ordered)}",
        "Книга склада не пересчитана; auto-reconcile продолжается.",
        "",
    ]
    for item in ordered:
        kind_ru = "изменено" if item.kind == "changed" else "не найдено в МС"
        session = item.session_id.strip() or "неизвестно"
        lines.append(f"{item.external_document_id} — {kind_ru}")
        lines.append(f"  сверка: {session}")
        lines.append("  инвентаризация: неизвестно")
        lines.append("  периоды: неизвестно")
    text = "\n".join(lines)
    if len(text) <= _TELEGRAM_MESSAGE_SOFT_LIMIT:
        return text
    kept: list[str] = lines[:4]
    budget = _TELEGRAM_MESSAGE_SOFT_LIMIT - 40
    body_lines: list[str] = []
    used = len("\n".join(kept)) + 1
    omitted = 0
    for line in lines[4:]:
        if used + len(line) + 1 > budget:
            omitted += 1
            continue
        body_lines.append(line)
        used += len(line) + 1
    if omitted:
        body_lines.append(f"… и ещё {omitted}")
    return "\n".join([*kept, *body_lines])


@beartype
@dataclass
class DedupingFinalizedTransferDriftOpsAlerter:
    """Process-local dedup: one alert per (technician_id, frozenset(document_ids))."""

    inner: FinalizedTransferDriftOpsAlerter
    _seen: set[tuple[str, frozenset[str]]] = field(default_factory=set)

    @beartype
    def notify_drift(
        self,
        *,
        technician_id: str,
        items: tuple[IgnoredFinalizedTransfer, ...],
    ) -> None:
        fingerprint = (
            technician_id,
            frozenset(item.external_document_id for item in items),
        )
        if fingerprint in self._seen:
            _LOGGER.info(
                "finalized_transfer_drift_ops_alert_deduped technician_id=%s documents=%s",
                technician_id,
                len(fingerprint[1]),
            )
            return
        self.inner.notify_drift(technician_id=technician_id, items=items)
        self._seen.add(fingerprint)


@beartype
class NoOpFinalizedTransferDriftOpsAlerter:
    def notify_drift(
        self,
        *,
        technician_id: str,
        items: tuple[IgnoredFinalizedTransfer, ...],
    ) -> None:
        _LOGGER.info(
            "finalized_transfer_drift_ops alert skipped (no alerter) technician_id=%s count=%s",
            technician_id,
            len(items),
        )


__all__ = [
    "DedupingFinalizedTransferDriftOpsAlerter",
    "FinalizedTransferDriftOpsAlerter",
    "NoOpFinalizedTransferDriftOpsAlerter",
    "format_finalized_transfer_drift_ops_message",
]
