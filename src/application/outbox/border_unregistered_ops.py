from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from beartype import beartype

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_MESSAGE_SOFT_LIMIT = 3500


@runtime_checkable
class BorderUnregisteredOpsAlerter(Protocol):
    def notify_unregistered(
        self,
        *,
        technician_id: str,
        products: tuple[tuple[str, str], ...],
    ) -> None: ...


@beartype
def format_border_unregistered_ops_message(
    *,
    technician_id: str,
    products: tuple[tuple[str, str], ...],
) -> str:
    ordered = tuple(sorted(products, key=lambda item: item[0]))
    lines = [
        "Незарегистрированные товары МС на границе склад→техник",
        f"Техник: {technician_id}",
        f"Кодов: {len(ordered)}",
        "Зарегистрируйте (связь или ignore): /admin/coffee-border-registration",
        "",
    ]
    for code, name in ordered:
        trimmed = name.strip()
        lines.append(code if not trimmed else f"{code} — {trimmed}")
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
class DedupingBorderUnregisteredOpsAlerter:
    """Process-local dedup: one alert per (technician_id, frozenset(codes))."""

    inner: BorderUnregisteredOpsAlerter
    _seen: set[tuple[str, frozenset[str]]] = field(default_factory=set)

    @beartype
    def notify_unregistered(
        self,
        *,
        technician_id: str,
        products: tuple[tuple[str, str], ...],
    ) -> None:
        fingerprint = (technician_id, frozenset(code for code, _name in products))
        if fingerprint in self._seen:
            _LOGGER.info(
                "border_unregistered_ops_alert_deduped technician_id=%s codes=%s",
                technician_id,
                len(fingerprint[1]),
            )
            return
        self.inner.notify_unregistered(technician_id=technician_id, products=products)
        self._seen.add(fingerprint)


@beartype
class NoOpBorderUnregisteredOpsAlerter:
    def notify_unregistered(
        self,
        *,
        technician_id: str,
        products: tuple[tuple[str, str], ...],
    ) -> None:
        _LOGGER.info(
            "border_unregistered_ops alert skipped (no alerter) technician_id=%s count=%s",
            technician_id,
            len(products),
        )


__all__ = [
    "BorderUnregisteredOpsAlerter",
    "DedupingBorderUnregisteredOpsAlerter",
    "NoOpBorderUnregisteredOpsAlerter",
    "format_border_unregistered_ops_message",
]
