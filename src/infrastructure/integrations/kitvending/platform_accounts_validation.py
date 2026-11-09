from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype

from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.application.master_data.ports import CompanyStore
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount


@beartype
def validate_platform_accounts(
    accounts: Sequence[KitPlatformAccount],
    *,
    company_store: CompanyStore,
    require_company_store: bool = True,
) -> None:
    if require_company_store and company_store.is_empty():
        raise ValueError("company store empty")

    sales_poll_count = sum(
        1
        for account in accounts
        if account.platform is KitPlatform.KIT_VENDING
        and account.role is KitPlatformRole.SALES_POLL
    )
    if sales_poll_count > 1:
        raise ValueError("multiple sales_poll vending accounts")

    for account in accounts:
        company = company_store.get(account.company_id)
        if company is None:
            raise ValueError(
                f"binding mismatch: MK company_id={account.company_id} not found for account "
                f"{account.account_key!r}",
            )
        matched = False
        for binding in company.platform_bindings:
            if (
                binding.platform is account.platform
                and binding.kit_company_id == account.kit_company_id
            ):
                matched = True
                break
        if not matched:
            raise ValueError(
                f"binding mismatch: account {account.account_key!r} "
                f"({account.platform.value}, kit_company_id={account.kit_company_id}) "
                f"not on MK company_id={account.company_id}",
            )
