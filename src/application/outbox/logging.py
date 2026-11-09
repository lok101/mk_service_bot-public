from __future__ import annotations

from beartype import beartype


@beartype
def outbox_log_extra(
    *,
    entry_id: str | None = None,
    handler_id: str | None = None,
    event_id: str | None = None,
    claim_id: str | None = None,
) -> dict[str, str]:
    extra: dict[str, str] = {}
    if entry_id is not None:
        extra["outbox_entry_id"] = entry_id
    if handler_id is not None:
        extra["outbox_handler_id"] = handler_id
    if event_id is not None:
        extra["outbox_event_id"] = event_id
    if claim_id is not None:
        extra["outbox_claim_id"] = claim_id
    return extra
