from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from beartype import beartype

from src.application.micromarket_loading.form_fingerprint import inventory_form_fingerprint
from src.application.micromarket_loading.inventory_form_pages import (
    InventoryFormPage,
    flatten_inventory_form_page_codes,
)
from src.application.micromarket_loading.ports import (
    MicromarketInventoryFormFactory,
    MicromarketInventoryFormMode,
    MicromarketInventoryFormRegistry,
    MicromarketInventoryFormsConfig,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.form_tokens import (
    MicromarketInventoryFormPurpose,
    MicromarketInventoryFormTokenPayload,
    create_micromarket_inventory_form_token,
)
from src.domain.ids import TechnicianId

_logger = logging.getLogger(__name__)

_EMPTY_SKU_MESSAGE = "нет SKU для инвентаризации"
_FIELD_FORM_NOW_PATH = "/forms/micromarket-inventory/now"
_FIELD_FORM_NOW_ID = "micromarket-inventory-now"


@beartype
@dataclass(frozen=True, slots=True)
class IssuedMicromarketInventoryLink:
    form_id: str
    form_url: str
    fingerprint_id: str


@beartype
@dataclass(frozen=True, slots=True)
class EmptyMicromarketSkuSet:
    message: str = _EMPTY_SKU_MESSAGE


@beartype
@dataclass(frozen=True, slots=True)
class IssueMicromarketInventoryLink:
    registry: MicromarketInventoryFormRegistry
    factory: MicromarketInventoryFormFactory
    forms_settings: MicromarketInventoryFormsConfig
    now_template_id: str
    as_of_template_id: str
    token_entry_id: str
    now_token_secret: str
    as_of_token_secret: str
    clock: Callable[[], datetime]
    qty_max: int
    field_forms_public_base_url: str = ""
    products: DomainProductStore | None = None

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        pages: Sequence[InventoryFormPage],
        technician_id: TechnicianId,
    ) -> IssuedMicromarketInventoryLink | EmptyMicromarketSkuSet:
        if mode == "now":
            return self._execute_now_field_form(
                machine_code=machine_code,
                pages=pages,
                technician_id=technician_id,
            )
        return self._execute_as_of_google_form(
            machine_code=machine_code,
            pages=pages,
            technician_id=technician_id,
        )

    @beartype
    def _execute_now_field_form(
        self,
        *,
        machine_code: str,
        pages: Sequence[InventoryFormPage],
        technician_id: TechnicianId,
    ) -> IssuedMicromarketInventoryLink | EmptyMicromarketSkuSet:
        self.forms_settings.require_micromarket_inventory_now()
        page_tuple = tuple(pages)
        codes = flatten_inventory_form_page_codes(page_tuple)
        if not codes:
            return EmptyMicromarketSkuSet()

        fingerprint = inventory_form_fingerprint(pages=page_tuple, mode="now")
        token = create_micromarket_inventory_form_token(
            MicromarketInventoryFormTokenPayload(
                purpose="micromarket_inventory_now",
                technician_id=technician_id,
                machine_code=machine_code,
                fingerprint_id=fingerprint,
                product_codes=codes,
                issued_at=self.clock(),
                nonce=secrets.token_urlsafe(12),
            ),
            self.now_token_secret,
        )
        form_url = _field_form_now_url(
            base_url=self.field_forms_public_base_url,
            token=token,
        )
        _logger.info(
            "micromarket_inventory_web_form_issued",
            extra={
                "machine_code": machine_code,
                "fingerprint_id": fingerprint,
            },
        )
        return IssuedMicromarketInventoryLink(
            form_id=_FIELD_FORM_NOW_ID,
            form_url=form_url,
            fingerprint_id=fingerprint,
        )

    @beartype
    def _execute_as_of_google_form(
        self,
        *,
        machine_code: str,
        pages: Sequence[InventoryFormPage],
        technician_id: TechnicianId,
    ) -> IssuedMicromarketInventoryLink | EmptyMicromarketSkuSet:
        self.forms_settings.require_micromarket_inventory_forms()
        if not self.token_entry_id.startswith("entry."):
            raise ValueError("Google Form token entry id must start with 'entry.'")

        page_tuple = tuple(pages)
        codes = flatten_inventory_form_page_codes(page_tuple)
        if not codes:
            return EmptyMicromarketSkuSet()

        fingerprint = inventory_form_fingerprint(pages=page_tuple, mode="as_of")
        hit = self.registry.get(machine_code, "as_of", fingerprint)
        if hit is not None:
            _logger.info(
                "micromarket_inventory_form_fingerprint_hit",
                extra={
                    "machine_code": machine_code,
                    "mode": "as_of",
                    "fingerprint_id": fingerprint,
                    "form_id": hit.form_id,
                },
            )
            base_url = hit.form_url
            form_id = hit.form_id
        else:
            copied = self.factory.copy_template_and_build_questions(
                template_id=self.as_of_template_id,
                pages=page_tuple,
                product_names={code: _resolve_product_name(code, self.products) for code in codes},
                qty_max=self.qty_max,
            )
            self.registry.put(
                machine_code,
                "as_of",
                fingerprint,
                form_id=copied.form_id,
                form_url=copied.form_url,
            )
            _logger.info(
                "micromarket_inventory_form_fingerprint_miss",
                extra={
                    "machine_code": machine_code,
                    "mode": "as_of",
                    "fingerprint_id": fingerprint,
                    "form_id": copied.form_id,
                },
            )
            base_url = copied.form_url
            form_id = copied.form_id

        purpose: MicromarketInventoryFormPurpose = "micromarket_inventory_as_of"
        token = create_micromarket_inventory_form_token(
            MicromarketInventoryFormTokenPayload(
                purpose=purpose,
                technician_id=technician_id,
                machine_code=machine_code,
                fingerprint_id=fingerprint,
                product_codes=codes,
                issued_at=self.clock(),
                nonce=secrets.token_urlsafe(12),
            ),
            self.as_of_token_secret,
        )
        return IssuedMicromarketInventoryLink(
            form_id=form_id,
            form_url=_prefilled_form_url(
                form_url=base_url,
                entry_id=self.token_entry_id,
                value=token,
            ),
            fingerprint_id=fingerprint,
        )


@beartype
def _resolve_product_name(code: str, products: DomainProductStore | None) -> str:
    if products is None:
        return ""
    product = products.get_by_number(code)
    if product is None:
        product = products.get_by_catalog_code(code)
    if product is None:
        return ""
    return product.name.strip()


@beartype
def _field_form_now_url(*, base_url: str, token: str) -> str:
    origin = base_url.strip().rstrip("/")
    if not origin:
        raise ValueError("FIELD_FORMS_PUBLIC_BASE_URL must not be empty")
    if not token:
        raise ValueError("FieldForm token must not be empty")
    parts = urlsplit(f"{origin}{_FIELD_FORM_NOW_PATH}")
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode({"token": token}), parts.fragment),
    )


@beartype
def _prefilled_form_url(*, form_url: str, entry_id: str, value: str) -> str:
    if not form_url:
        raise ValueError("Google Form URL must not be empty")
    if not value:
        raise ValueError("Google Form prefilled value must not be empty")
    parts = urlsplit(form_url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params["usp"] = "pp_url"
    query_params[entry_id] = value
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query_params), parts.fragment),
    )


@beartype
def default_issue_clock() -> datetime:
    return datetime.now(tz=UTC)
