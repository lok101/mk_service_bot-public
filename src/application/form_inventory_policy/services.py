from __future__ import annotations

from decimal import Decimal

from beartype import beartype

from src.application.form_inventory_policy.models import (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_POLICY_PROFILE_IDS,
    COFFEE_REVISION_PROFILE_ID,
    DEFAULT_COFFEE_PROFILES,
    TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
    FormInventoryPolicyLine,
    FormInventoryPolicyProfileId,
)
from src.application.form_inventory_policy.ports import FormInventoryPolicyStore


@beartype
def ensure_coffee_policy_profiles(store: FormInventoryPolicyStore) -> None:
    for profile in DEFAULT_COFFEE_PROFILES:
        if store.get_profile(profile.profile_id) is None:
            store.save_profile(profile)


@beartype
def seed_coffee_ingredient_policies(
    store: FormInventoryPolicyStore,
    *,
    domain_number: str,
    loading: FormInventoryPolicyLine,
    revision: FormInventoryPolicyLine,
    warehouse: FormInventoryPolicyLine,
) -> None:
    ensure_coffee_policy_profiles(store)
    trimmed = domain_number.strip()
    by_profile: dict[FormInventoryPolicyProfileId, FormInventoryPolicyLine] = {
        COFFEE_LOADING_PROFILE_ID: loading,
        COFFEE_REVISION_PROFILE_ID: revision,
        TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID: warehouse,
    }
    for profile_id in COFFEE_POLICY_PROFILE_IDS:
        source = by_profile[profile_id]
        store.upsert_line(
            profile_id,
            FormInventoryPolicyLine(
                domain_number=trimmed,
                min_qty=source.min_qty,
                max_qty=source.max_qty,
                radio_n=(source.radio_n if profile_id == COFFEE_LOADING_PROFILE_ID else None),
                sort_order=source.sort_order,
                form_label=source.form_label,
                form_hint=source.form_hint,
            ),
        )


@beartype
def upsert_policy_line(
    store: FormInventoryPolicyStore,
    *,
    profile_id: FormInventoryPolicyProfileId,
    domain_number: str,
    min_qty: Decimal,
    max_qty: Decimal,
    radio_n: int | None = None,
    sort_order: int = 0,
    form_label: str = "",
    form_hint: str = "",
) -> FormInventoryPolicyLine:
    ensure_coffee_policy_profiles(store)
    line = FormInventoryPolicyLine(
        domain_number=domain_number.strip(),
        min_qty=min_qty,
        max_qty=max_qty,
        radio_n=radio_n,
        sort_order=sort_order,
        form_label=form_label,
        form_hint=form_hint,
    )
    store.upsert_line(profile_id, line)
    return line
