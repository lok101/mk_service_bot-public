from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_inventory_policy.models import (
    FormInventoryPolicyLine,
    FormInventoryPolicyProfile,
    FormInventoryPolicyProfileId,
)


@runtime_checkable
class FormInventoryPolicyStore(Protocol):
    @beartype
    def get_profile(
        self,
        profile_id: FormInventoryPolicyProfileId,
    ) -> FormInventoryPolicyProfile | None: ...

    @beartype
    def save_profile(self, profile: FormInventoryPolicyProfile) -> None: ...

    @beartype
    def get_line(
        self,
        profile_id: FormInventoryPolicyProfileId,
        domain_number: str,
    ) -> FormInventoryPolicyLine | None: ...

    @beartype
    def upsert_line(
        self,
        profile_id: FormInventoryPolicyProfileId,
        line: FormInventoryPolicyLine,
    ) -> None: ...

    @beartype
    def list_lines(
        self,
        profile_id: FormInventoryPolicyProfileId,
    ) -> tuple[FormInventoryPolicyLine, ...]: ...
