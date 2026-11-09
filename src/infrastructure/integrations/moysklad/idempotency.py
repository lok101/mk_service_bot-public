from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from beartype import beartype

from src.application.form_submissions.ports import (
    ExternalSideEffectInProgressError,
    ExternalSideEffectRegistry,
)
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort

_MOYSKLAD_PROVIDER = "moysklad"


@beartype
async def find_document_by_external_code(
    client: MoySkladClientPort,
    *,
    entity_path: str,
    external_code: str,
) -> Mapping[str, Any] | None:
    rows = await client.get_entity_list(
        entity_path=entity_path,
        filter_expr=f"externalCode={external_code}",
        limit=1,
    )
    if not rows:
        return None
    first = rows[0]
    return first if isinstance(first, Mapping) else None


@beartype
async def document_exists(
    client: MoySkladClientPort,
    *,
    entity_path: str,
    external_code: str,
) -> bool:
    return (
        await find_document_by_external_code(
            client,
            entity_path=entity_path,
            external_code=external_code,
        )
        is not None
    )


@beartype
async def execute_idempotent_moysklad_side_effect(
    *,
    registry: ExternalSideEffectRegistry,
    client: MoySkladClientPort,
    operation: str,
    entity_path: str,
    idempotency_key: str,
    external_code: str,
    create: Callable[[], Awaitable[Mapping[str, Any]]],
) -> None:
    claim = await asyncio.to_thread(
        registry.claim,
        provider=_MOYSKLAD_PROVIDER,
        operation=operation,
        idempotency_key=idempotency_key,
        external_code=external_code,
    )
    if not claim.claimed:
        if claim.status == "succeeded":
            return
        existing = await find_document_by_external_code(
            client,
            entity_path=entity_path,
            external_code=claim.external_code,
        )
        if existing is not None:
            await asyncio.to_thread(
                registry.mark_succeeded,
                provider=_MOYSKLAD_PROVIDER,
                operation=operation,
                idempotency_key=idempotency_key,
                external_id=_external_id_from_document(existing),
            )
            return
        raise ExternalSideEffectInProgressError(
            f"MoySklad {operation} side effect is already {claim.status}",
        )

    # After claim, recovery lookup and create share mark_failed so a timeout
    # cannot leave the side effect stuck in processing.
    try:
        if claim.previous_status in {"failed", "processing"}:
            existing = await find_document_by_external_code(
                client,
                entity_path=entity_path,
                external_code=claim.external_code,
            )
            if existing is not None:
                await asyncio.to_thread(
                    registry.mark_succeeded,
                    provider=_MOYSKLAD_PROVIDER,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    external_id=_external_id_from_document(existing),
                )
                return

        response = await create()
    except Exception as error:
        await asyncio.to_thread(
            registry.mark_failed,
            provider=_MOYSKLAD_PROVIDER,
            operation=operation,
            idempotency_key=idempotency_key,
            error_message=str(error),
        )
        raise

    await asyncio.to_thread(
        registry.mark_succeeded,
        provider=_MOYSKLAD_PROVIDER,
        operation=operation,
        idempotency_key=idempotency_key,
        external_id=_external_id_from_document(response),
    )


@beartype
def _external_id_from_document(document: Mapping[str, Any]) -> str | None:
    external_id = document.get("id")
    if isinstance(external_id, str) and external_id:
        return external_id

    meta = document.get("meta")
    if not isinstance(meta, Mapping):
        return None
    href = meta.get("href")
    if not isinstance(href, str) or not href:
        return None
    return href.rsplit("/", maxsplit=1)[-1] or None
