from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.form_inventory_policy import (
    TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
    FormInventoryPolicyStore,
)
from src.application.product_identity import packaging_is_form_ready
from src.application.product_identity.ports import DomainProductStore
from src.domain.form_tokens import (
    TechnicianWarehouseInventoryTokenPayload,
    create_technician_warehouse_inventory_token,
)
from src.domain.ids import TechnicianId
from src.domain.models import PrefilledFormLink
from src.infrastructure.field_forms.coffee_link_providers import (
    coffee_field_form_url,
    list_visible_coffee_ingredient_numbers,
)

_EMPTY_INGREDIENTS_MESSAGE = "нет видимых ингредиентов кофе"
_MISSING_PACK_OR_POLICY_MESSAGE = "нет упаковки или политики qty у видимых ингредиентов кофе"
_FORM_PATH = "/forms/technician-warehouse-inventory"


@beartype
def technician_warehouse_field_form_issue_enabled(
    *,
    field_forms_public_base_url: str,
    technician_warehouse_inventory_form_url: str,
) -> bool:
    """FieldForm issue when public base is set and legacy Google warehouse URL is cleared."""
    if not field_forms_public_base_url.strip():
        return False
    return not technician_warehouse_inventory_form_url.strip()


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseInventoryFieldFormLinkProvider:
    products: DomainProductStore
    policies: FormInventoryPolicyStore
    token_secret: str
    field_forms_public_base_url: str
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    def __post_init__(self) -> None:
        if not self.token_secret:
            raise ValueError("Warehouse inventory form token secret must not be empty")
        if not self.field_forms_public_base_url.strip():
            raise ValueError("FIELD_FORMS_PUBLIC_BASE_URL must not be empty")

    @beartype
    def create_link(self, technician_id: TechnicianId) -> PrefilledFormLink:
        codes = list_visible_coffee_ingredient_numbers(self.products)
        if not codes:
            raise ValueError(_EMPTY_INGREDIENTS_MESSAGE)
        for number in codes:
            product = self.products.get_by_number(number)
            if product is None or not packaging_is_form_ready(
                unit=product.unit,
                pack_size=product.pack_size,
            ):
                raise ValueError(_MISSING_PACK_OR_POLICY_MESSAGE)
            if self.policies.get_line(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID, number) is None:
                raise ValueError(_MISSING_PACK_OR_POLICY_MESSAGE)
        payload = TechnicianWarehouseInventoryTokenPayload(
            technician_id=technician_id,
            issued_at=self.clock(),
            nonce=secrets.token_urlsafe(12),
        )
        token = create_technician_warehouse_inventory_token(payload, self.token_secret)
        return PrefilledFormLink(
            url=coffee_field_form_url(
                base_url=self.field_forms_public_base_url,
                form_path=_FORM_PATH,
                token=token,
            ),
        )
