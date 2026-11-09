from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

_DRAIN_MAX_ROUNDS = 100


@runtime_checkable
class OutboxHandlerDrainer(Protocol):
    def drain_handler(self, handler_id: str) -> int: ...


@beartype
def drain_handler_until_empty(
    drainer: OutboxHandlerDrainer,
    handler_id: str,
    *,
    max_rounds: int = _DRAIN_MAX_ROUNDS,
) -> int:
    """Local copy of sales_monitoring helper — do not import application BC."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")
    total = 0
    for _ in range(max_rounds):
        drained = drainer.drain_handler(handler_id)
        if drained <= 0:
            return total
        total += drained
    raise RuntimeError(
        f"Outbox drain for handler {handler_id!r} did not empty after {max_rounds} rounds "
        f"(drained={total})",
    )
