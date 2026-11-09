from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from beartype import beartype

from src.application.form_submissions.ports import (
    ExternalSideEffectClaim,
    ExternalSideEffectRegistry,
    ExternalSideEffectStatus,
)
from src.infrastructure.external_side_effect_lease import (
    DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS,
    stale_processing_cutoff,
)


@beartype
def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(slots=True)
class InMemoryExternalSideEffectRegistry(ExternalSideEffectRegistry):
    processing_lease_seconds: int = DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS
    _entries: dict[tuple[str, str, str], dict[str, object]] = field(default_factory=dict)

    @beartype
    def claim(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        external_code: str,
    ) -> ExternalSideEffectClaim:
        key = (provider, operation, idempotency_key)
        existing = self._entries.get(key)
        now = _utc_now()
        if existing is None:
            self._entries[key] = {
                "provider": provider,
                "operation": operation,
                "idempotency_key": idempotency_key,
                "external_code": external_code,
                "status": "processing",
                "external_id": None,
                "last_error": None,
                "created_at": now,
                "updated_at": now,
            }
            return ExternalSideEffectClaim(
                claimed=True,
                status="processing",
                external_code=external_code,
            )

        status = _status_from_entry(existing)
        stored_external_code = _external_code_from_entry(existing)
        external_id = _external_id_from_entry(existing)
        if status == "failed":
            existing["status"] = "processing"
            existing["last_error"] = None
            existing["updated_at"] = now
            return ExternalSideEffectClaim(
                claimed=True,
                status="processing",
                external_code=stored_external_code,
                previous_status="failed",
                external_id=external_id,
            )

        if status == "processing":
            updated_at = existing.get("updated_at")
            if isinstance(updated_at, datetime):
                cutoff = stale_processing_cutoff(
                    now=now,
                    processing_lease_seconds=self.processing_lease_seconds,
                )
                if updated_at <= cutoff:
                    existing["status"] = "processing"
                    existing["last_error"] = None
                    existing["updated_at"] = now
                    return ExternalSideEffectClaim(
                        claimed=True,
                        status="processing",
                        external_code=stored_external_code,
                        previous_status="processing",
                        external_id=external_id,
                    )

        return ExternalSideEffectClaim(
            claimed=False,
            status=status,
            external_code=stored_external_code,
            external_id=external_id,
        )

    @beartype
    def mark_succeeded(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        external_id: str | None = None,
    ) -> None:
        entry = self._entries.get((provider, operation, idempotency_key))
        if entry is None:
            raise ValueError(
                f"External side effect {operation!r} for idempotency_key {idempotency_key!r} "
                "was not found while updating status",
            )
        entry["status"] = "succeeded"
        entry["external_id"] = external_id
        entry["last_error"] = None
        entry["updated_at"] = _utc_now()

    @beartype
    def mark_failed(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        entry = self._entries.get((provider, operation, idempotency_key))
        if entry is None:
            raise ValueError(
                f"External side effect {operation!r} for idempotency_key {idempotency_key!r} "
                "was not found while updating status",
            )
        entry["status"] = "failed"
        entry["last_error"] = error_message
        entry["updated_at"] = _utc_now()

    @beartype
    def count_settlement_related(self) -> int:
        return sum(1 for entry in self._entries.values() if _is_settlement_related_entry(entry))

    @beartype
    def delete_settlement_related(self) -> int:
        keys_to_delete = [
            key for key, entry in self._entries.items() if _is_settlement_related_entry(entry)
        ]
        for key in keys_to_delete:
            del self._entries[key]
        return len(keys_to_delete)


@beartype
def _is_settlement_related_entry(entry: dict[str, object]) -> bool:
    provider = entry.get("provider")
    operation = entry.get("operation")
    external_code = entry.get("external_code")
    if provider == "google_sheets" and operation == "settlement_audit_row":
        return True
    return (
        provider == "moysklad"
        and isinstance(external_code, str)
        and external_code.startswith("mk-service-bot:settlement:")
    )


@beartype
def _status_from_entry(entry: dict[str, object]) -> ExternalSideEffectStatus:
    status = entry.get("status")
    if status not in {"processing", "succeeded", "failed"}:
        raise ValueError("External side effect status is invalid")
    return cast(ExternalSideEffectStatus, status)


@beartype
def _external_code_from_entry(entry: dict[str, object]) -> str:
    external_code = entry.get("external_code")
    if not isinstance(external_code, str) or not external_code:
        raise ValueError("External side effect external_code is invalid")
    return external_code


@beartype
def _external_id_from_entry(entry: dict[str, object]) -> str | None:
    external_id = entry.get("external_id")
    return external_id if isinstance(external_id, str) else None
