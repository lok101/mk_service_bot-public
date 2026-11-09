from __future__ import annotations

from beartype import beartype

from src.application.form_inventory_policy.models import (
    FormInventoryPolicyLine,
    FormInventoryPolicyProfile,
    FormInventoryPolicyProfileId,
)


@beartype
class MemoryFormInventoryPolicyStore:
    def __init__(self) -> None:
        self._profiles: dict[FormInventoryPolicyProfileId, FormInventoryPolicyProfile] = {}
        self._lines: dict[
            tuple[FormInventoryPolicyProfileId, str],
            FormInventoryPolicyLine,
        ] = {}

    @beartype
    def get_profile(
        self,
        profile_id: FormInventoryPolicyProfileId,
    ) -> FormInventoryPolicyProfile | None:
        return self._profiles.get(profile_id)

    @beartype
    def save_profile(self, profile: FormInventoryPolicyProfile) -> None:
        self._profiles[profile.profile_id] = profile

    @beartype
    def get_line(
        self,
        profile_id: FormInventoryPolicyProfileId,
        domain_number: str,
    ) -> FormInventoryPolicyLine | None:
        return self._lines.get((profile_id, domain_number))

    @beartype
    def upsert_line(
        self,
        profile_id: FormInventoryPolicyProfileId,
        line: FormInventoryPolicyLine,
    ) -> None:
        self._lines[(profile_id, line.domain_number)] = line

    @beartype
    def list_lines(
        self,
        profile_id: FormInventoryPolicyProfileId,
    ) -> tuple[FormInventoryPolicyLine, ...]:
        lines = [
            line
            for (stored_profile, _), line in self._lines.items()
            if stored_profile == profile_id
        ]
        return tuple(
            sorted(lines, key=lambda line: (line.sort_order, line.domain_number)),
        )
