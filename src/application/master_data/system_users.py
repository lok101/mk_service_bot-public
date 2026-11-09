from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from beartype import beartype

from src.application.master_data.models import (
    SYSTEM_USER_COUNTER_KEY,
    allocate_system_user_id,
)
from src.application.master_data.ports import (
    MasterDataCounterStore,
    SystemUserStore,
    TechnicianStore,
)
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import TechnicianId
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
)

_SAVE_AUDIT_COMMAND = "save_system_users"
_IMPORT_AUDIT_COMMAND = "import_system_users"
_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class SystemUserRecord:
    user: SystemUser
    updated_at: datetime
    updated_by_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class SystemUserAuditRecord:
    at: datetime
    actor_telegram_user_id: int
    audit_command: str
    telegram_user_id: int
    before: SystemUserRecord | None
    after: SystemUserRecord | None


@beartype
@dataclass(frozen=True, slots=True)
class SystemUserDraft:
    telegram_user_id: int
    name: str
    bot_role: BotRole
    is_active: bool
    technician_id: TechnicianId | None
    company_roles: frozenset[CompanyRole]
    user_id: SystemUserId | None


class SystemUsersInvalid(Exception):
    @beartype
    def __init__(self, message: str) -> None:
        super().__init__(message)


@beartype
def technician_ids_for_system_users_validation(
    *,
    technicians_enabled: bool,
    technician_store: TechnicianStore | None,
    directory_snapshot_ids: frozenset[TechnicianId],
) -> frozenset[TechnicianId]:
    """When technicians SoT is on, validate against store (incl. inactive); else Sheets snapshot."""
    if technicians_enabled and technician_store is not None:
        return frozenset(technician.technician_id for technician in technician_store.list_all())
    return directory_snapshot_ids


@beartype
@dataclass(slots=True)
class ImportSystemUsersFromSheets:
    store: SystemUserStore

    @beartype
    def execute(
        self,
        snapshot: SystemUsersSnapshot,
        *,
        now: datetime,
        actor_telegram_user_id: int,
    ) -> None:
        if not self.store.is_empty():
            return
        records = tuple(
            SystemUserRecord(
                user=SystemUser(
                    user_id=user.user_id,
                    name=user.name,
                    role=user.role,
                    is_active=user.is_active,
                    telegram_user_id=user.telegram_user_id,
                    technician_id=user.technician_id,
                    company_roles=frozenset(),
                ),
                updated_at=now,
                updated_by_telegram_user_id=actor_telegram_user_id,
            )
            for user in snapshot.users_by_telegram_id.values()
        )
        self.store.save_batch(
            records,
            actor_telegram_user_id=actor_telegram_user_id,
            at=now,
            audit_command=_IMPORT_AUDIT_COMMAND,
        )
        _LOGGER.info("system_users_import", extra={"imported": len(records)})


@beartype
@dataclass(slots=True)
class SaveSystemUsers:
    store: SystemUserStore
    counters: MasterDataCounterStore

    @beartype
    def execute(
        self,
        drafts: tuple[SystemUserDraft, ...],
        *,
        directory_technician_ids: frozenset[TechnicianId],
        actor_telegram_user_id: int,
        actor_panels: frozenset[AdminPanel],
        now: datetime,
        preserve_technician_links: bool = False,
    ) -> None:
        existing = self.store.list_all()
        if preserve_technician_links:
            drafts = _merge_access_drafts(drafts, existing)
        _validate_drafts(
            drafts,
            directory_technician_ids=directory_technician_ids,
            existing=existing,
            actor_panels=actor_panels,
        )
        _assert_users_admin_present(drafts, existing)
        _sync_counter_with_known_ids(
            self.counters,
            drafts=drafts,
            existing=self.store.list_all(),
        )
        records = _records_from_drafts(
            drafts,
            counters=self.counters,
            actor_telegram_user_id=actor_telegram_user_id,
            now=now,
        )
        self.store.save_batch(
            records,
            actor_telegram_user_id=actor_telegram_user_id,
            at=now,
            audit_command=_SAVE_AUDIT_COMMAND,
        )


@beartype
def _validate_drafts(
    drafts: tuple[SystemUserDraft, ...],
    *,
    directory_technician_ids: frozenset[TechnicianId],
    existing: tuple[SystemUserRecord, ...],
    actor_panels: frozenset[AdminPanel],
) -> None:
    existing_by_tg = {record.user.telegram_user_id: record.user for record in existing}
    seen_telegram_ids: set[int] = set()
    for draft in drafts:
        if draft.telegram_user_id <= 0:
            raise SystemUsersInvalid(
                f"telegram user id must be positive, got {draft.telegram_user_id}",
            )
        if draft.telegram_user_id in seen_telegram_ids:
            raise SystemUsersInvalid(
                f"duplicate telegram user id {draft.telegram_user_id}",
            )
        seen_telegram_ids.add(draft.telegram_user_id)
        existing_user = existing_by_tg.get(draft.telegram_user_id)
        existing_roles = existing_user.company_roles if existing_user is not None else frozenset()
        if draft.company_roles != existing_roles and AdminPanel.USERS not in actor_panels:
            raise SystemUsersInvalid(
                "cannot assign roles outside actor scope: access administrator required",
            )
        if draft.technician_id is not None and draft.technician_id not in directory_technician_ids:
            raise SystemUsersInvalid(
                f"unknown technician {draft.technician_id.value!r}",
            )
    _validate_unique_active_technician_ids(drafts, existing)


@beartype
def _validate_unique_active_technician_ids(
    drafts: tuple[SystemUserDraft, ...],
    existing: tuple[SystemUserRecord, ...],
) -> None:
    incoming = {draft.telegram_user_id: draft for draft in drafts}
    owner_by_technician: dict[str, int] = {}
    for record in existing:
        tg = record.user.telegram_user_id
        if tg in incoming:
            draft = incoming[tg]
            is_active = draft.is_active
            technician_id = draft.technician_id
        else:
            is_active = record.user.is_active
            technician_id = record.user.technician_id
        if not is_active or technician_id is None:
            continue
        key = technician_id.value
        prev = owner_by_technician.get(key)
        if prev is not None and prev != tg:
            raise SystemUsersInvalid(f"duplicate technician id {key!r}")
        owner_by_technician[key] = tg
    for draft in drafts:
        if draft.telegram_user_id in {r.user.telegram_user_id for r in existing}:
            continue
        if not draft.is_active or draft.technician_id is None:
            continue
        key = draft.technician_id.value
        prev = owner_by_technician.get(key)
        if prev is not None and prev != draft.telegram_user_id:
            raise SystemUsersInvalid(f"duplicate technician id {key!r}")
        owner_by_technician[key] = draft.telegram_user_id


@beartype
def _sync_counter_with_known_ids(
    counters: MasterDataCounterStore,
    *,
    drafts: tuple[SystemUserDraft, ...],
    existing: tuple[SystemUserRecord, ...],
) -> None:
    max_id = counters.get(SYSTEM_USER_COUNTER_KEY)
    for record in existing:
        max_id = max(max_id, _numeric_user_id(record.user.user_id))
    for draft in drafts:
        if draft.user_id is not None:
            max_id = max(max_id, _numeric_user_id(draft.user_id))
    if max_id > counters.get(SYSTEM_USER_COUNTER_KEY):
        counters.set(SYSTEM_USER_COUNTER_KEY, max_id)


@beartype
def _numeric_user_id(user_id: SystemUserId) -> int:
    if user_id.value.isdigit():
        return int(user_id.value)
    return 0


@beartype
def _records_from_drafts(
    drafts: tuple[SystemUserDraft, ...],
    *,
    counters: MasterDataCounterStore,
    actor_telegram_user_id: int,
    now: datetime,
) -> tuple[SystemUserRecord, ...]:
    records: list[SystemUserRecord] = []
    for draft in drafts:
        user_id = draft.user_id
        if user_id is None:
            user_id = SystemUserId(allocate_system_user_id(counters))
        records.append(
            SystemUserRecord(
                user=SystemUser(
                    user_id=user_id,
                    name=draft.name,
                    role=draft.bot_role,
                    is_active=draft.is_active,
                    telegram_user_id=draft.telegram_user_id,
                    technician_id=draft.technician_id,
                    company_roles=draft.company_roles,
                ),
                updated_at=now,
                updated_by_telegram_user_id=actor_telegram_user_id,
            ),
        )
    return tuple(records)


@beartype
def _merge_access_drafts(
    drafts: tuple[SystemUserDraft, ...],
    existing: tuple[SystemUserRecord, ...],
) -> tuple[SystemUserDraft, ...]:
    by_tg = {r.user.telegram_user_id: r.user for r in existing}
    merged: list[SystemUserDraft] = []
    for draft in drafts:
        prev = by_tg.get(draft.telegram_user_id)
        if prev is None:
            merged.append(draft)
            continue
        tech_id = draft.technician_id if draft.technician_id is not None else prev.technician_id
        role = draft.bot_role if draft.bot_role is not BotRole.NONE else prev.role
        merged.append(replace(draft, technician_id=tech_id, bot_role=role))
    return tuple(merged)


@beartype
def _assert_users_admin_present(
    drafts: tuple[SystemUserDraft, ...],
    existing: tuple[SystemUserRecord, ...],
) -> None:
    incoming = {draft.telegram_user_id: draft for draft in drafts}
    existing_tg = {record.user.telegram_user_id for record in existing}
    for record in existing:
        tg = record.user.telegram_user_id
        if tg in incoming:
            draft = incoming[tg]
            if draft.is_active and CompanyRole.ACCESS_ADMINISTRATOR in draft.company_roles:
                return
            continue
        if record.user.is_active and CompanyRole.ACCESS_ADMINISTRATOR in record.user.company_roles:
            return
    for draft in drafts:
        if (
            draft.telegram_user_id not in existing_tg
            and draft.is_active
            and CompanyRole.ACCESS_ADMINISTRATOR in draft.company_roles
        ):
            return
    raise SystemUsersInvalid("at least one active access administrator is required")
