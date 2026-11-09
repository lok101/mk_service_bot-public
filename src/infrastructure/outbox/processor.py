from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.domain.events import DomainEvent

OutboxHandler = Callable[[DomainEvent], Awaitable[None] | None]


@beartype
@dataclass
class OutboxProcessorRegistry:
    _handlers: dict[str, OutboxHandler] = field(default_factory=dict)

    @beartype
    def register(self, handler_id: str, handler: OutboxHandler) -> None:
        if not handler_id:
            raise ValueError("Outbox handler_id must not be empty")
        self._handlers[handler_id] = handler

    @beartype
    def is_registered(self, handler_id: str) -> bool:
        return handler_id in self._handlers

    @beartype
    def registered_handler_ids(self) -> frozenset[str]:
        return frozenset(self._handlers)

    @beartype
    async def process(self, handler_id: str, event: DomainEvent) -> None:
        handler = self._handlers.get(handler_id)
        if handler is None:
            raise ValueError(f"No outbox handler registered for id {handler_id!r}")

        # Sync handlers (e.g. micromarket_shop_list_publish + Kit HTTP) must not run on
        # the app event loop — a single replica serves admin HTTP and outbox together.
        if inspect.iscoroutinefunction(handler):
            await handler(event)
            return

        result = await asyncio.to_thread(handler, event)
        if inspect.isawaitable(result):
            await result
