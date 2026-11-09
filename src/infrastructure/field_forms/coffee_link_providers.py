from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit, urlunsplit

from beartype import beartype

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_REVISION_PROFILE_ID,
    FormInventoryPolicyProfileId,
    FormInventoryPolicyStore,
)
from src.application.product_identity import packaging_is_form_ready
from src.application.product_identity.ports import DomainProductStore
from src.domain.form_tokens import (
    CoffeeFormPurpose,
    CoffeeFormTokenPayload,
    create_coffee_form_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import PrefilledFormLink

_EMPTY_INGREDIENTS_MESSAGE = "нет видимых ингредиентов кофе"
_MISSING_PACK_OR_POLICY_MESSAGE = "нет упаковки или политики qty у видимых ингредиентов кофе"
_REVISION_PATH = "/forms/coffee-revision"
_LOADING_PATH = "/forms/coffee-loading"

_PURPOSE_PROFILE: dict[str, FormInventoryPolicyProfileId] = {
    "revision": COFFEE_REVISION_PROFILE_ID,
    "loading": COFFEE_LOADING_PROFILE_ID,
}


@beartype
def coffee_field_form_issue_enabled(
    *,
    field_forms_public_base_url: str,
    revision_form_url: str,
    loading_form_url: str,
) -> bool:
    """Prod cutover gate for coffee FieldForm issue (ISS-432 + ISS-452).

    FieldForm issue turns on only when ``FIELD_FORMS_PUBLIC_BASE_URL`` is set
    and legacy Google coffee form URLs are cleared. Keep Google URLs in prod
    until ISS-452 can accept domain keys in reconcile/PnL.
    """
    if not field_forms_public_base_url.strip():
        return False
    return not revision_form_url.strip() and not loading_form_url.strip()


@beartype
def list_visible_coffee_ingredient_numbers(
    products: DomainProductStore,
) -> tuple[str, ...]:
    return tuple(
        product.number for product in products.list_visible() if product.kind == "coffee_ingredient"
    )


@beartype
def coffee_field_form_url(*, base_url: str, form_path: str, token: str) -> str:
    origin = base_url.strip().rstrip("/")
    if not origin:
        raise ValueError("FIELD_FORMS_PUBLIC_BASE_URL must not be empty")
    if not token:
        raise ValueError("FieldForm token must not be empty")
    if not form_path.startswith("/"):
        raise ValueError("FieldForm path must start with '/'")
    parts = urlsplit(f"{origin}{form_path}")
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode({"token": token}), parts.fragment),
    )


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeFieldFormRevisionLinkProvider:
    products: DomainProductStore
    policies: FormInventoryPolicyStore
    token_secret: str
    field_forms_public_base_url: str
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    def __post_init__(self) -> None:
        if not self.token_secret:
            raise ValueError("Revision form token secret must not be empty")
        if not self.field_forms_public_base_url.strip():
            raise ValueError("FIELD_FORMS_PUBLIC_BASE_URL must not be empty")

    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        return _issue_link(
            products=self.products,
            policies=self.policies,
            token_secret=self.token_secret,
            field_forms_public_base_url=self.field_forms_public_base_url,
            clock=self.clock,
            purpose="revision",
            form_path=_REVISION_PATH,
            technician_id=technician_id,
            machine_id=machine_id,
        )


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeFieldFormLoadingLinkProvider:
    products: DomainProductStore
    policies: FormInventoryPolicyStore
    token_secret: str
    field_forms_public_base_url: str
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    def __post_init__(self) -> None:
        if not self.token_secret:
            raise ValueError("Loading form token secret must not be empty")
        if not self.field_forms_public_base_url.strip():
            raise ValueError("FIELD_FORMS_PUBLIC_BASE_URL must not be empty")

    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        return _issue_link(
            products=self.products,
            policies=self.policies,
            token_secret=self.token_secret,
            field_forms_public_base_url=self.field_forms_public_base_url,
            clock=self.clock,
            purpose="loading",
            form_path=_LOADING_PATH,
            technician_id=technician_id,
            machine_id=machine_id,
        )


@beartype
def _issue_link(
    *,
    products: DomainProductStore,
    policies: FormInventoryPolicyStore,
    token_secret: str,
    field_forms_public_base_url: str,
    clock: Callable[[], datetime],
    purpose: CoffeeFormPurpose,
    form_path: str,
    technician_id: TechnicianId,
    machine_id: MachineId,
) -> PrefilledFormLink:
    codes = list_visible_coffee_ingredient_numbers(products)
    if not codes:
        raise ValueError(_EMPTY_INGREDIENTS_MESSAGE)
    profile_id = _PURPOSE_PROFILE[purpose]
    for number in codes:
        product = products.get_by_number(number)
        if product is None or not packaging_is_form_ready(
            unit=product.unit,
            pack_size=product.pack_size,
        ):
            raise ValueError(_MISSING_PACK_OR_POLICY_MESSAGE)
        if policies.get_line(profile_id, number) is None:
            raise ValueError(_MISSING_PACK_OR_POLICY_MESSAGE)
    token = create_coffee_form_token(
        CoffeeFormTokenPayload(
            purpose=purpose,
            technician_id=technician_id,
            machine_id=machine_id,
            product_codes=codes,
            issued_at=clock(),
            nonce=secrets.token_urlsafe(12),
        ),
        token_secret,
    )
    return PrefilledFormLink(
        url=coffee_field_form_url(
            base_url=field_forms_public_base_url,
            form_path=form_path,
            token=token,
        ),
    )
