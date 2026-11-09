from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.infrastructure.integrations.moysklad.idempotency import (
    execute_idempotent_moysklad_side_effect,
)
from src.infrastructure.memory_side_effects import InMemoryExternalSideEffectRegistry


def test_idempotency_claim_runs_registry_in_thread() -> None:
    registry = InMemoryExternalSideEffectRegistry()
    client = FakeMoySkladClient()
    create = AsyncMock(return_value={"id": "doc-1"})
    with patch(
        "src.infrastructure.integrations.moysklad.idempotency.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as to_thread:
        to_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        asyncio.run(
            execute_idempotent_moysklad_side_effect(
                registry=registry,
                client=client,
                operation="inventory",
                entity_path="inventory",
                idempotency_key="evt-1",
                external_code="code",
                create=create,
            ),
        )
    assert to_thread.await_count >= 1
