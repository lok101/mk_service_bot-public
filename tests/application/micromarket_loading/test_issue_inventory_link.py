from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr

from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.issue_inventory_link import (
    EmptyMicromarketSkuSet,
    IssuedMicromarketInventoryLink,
    IssueMicromarketInventoryLink,
)
from src.config.micromarket_loading import MicromarketLoadingSettings
from src.domain.form_tokens import verify_micromarket_inventory_form_token
from src.domain.ids import TechnicianId
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketInventoryFormRegistry,
    StubMicromarketInventoryFormFactory,
    StubMicromarketInventoryFormsConfig,
)

_TECH = TechnicianId("tech-1")
_CLOCK = lambda: datetime(2026, 9, 3, 12, 0, tzinfo=UTC)  # noqa: E731
_FIELD_BASE = "https://bot.example.com"


def _pages(*codes: str) -> tuple[InventoryFormPage, ...]:
    return (
        InventoryFormPage(
            kit_group_id=10,
            product_codes=tuple(codes),
            title="группа 10",
        ),
    )


def _issue_uc(
    *,
    registry: InMemoryMicromarketInventoryFormRegistry | None = None,
    factory: StubMicromarketInventoryFormFactory | None = None,
    field_forms_public_base_url: str = _FIELD_BASE,
    forms_settings: StubMicromarketInventoryFormsConfig | MicromarketLoadingSettings | None = None,
) -> IssueMicromarketInventoryLink:
    return IssueMicromarketInventoryLink(
        registry=registry or InMemoryMicromarketInventoryFormRegistry(),
        factory=factory or StubMicromarketInventoryFormFactory(),
        forms_settings=forms_settings or StubMicromarketInventoryFormsConfig(),
        field_forms_public_base_url=field_forms_public_base_url,
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.123",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=_CLOCK,
        qty_max=30,
    )


class _RaisingFactory(StubMicromarketInventoryFormFactory):
    def copy_template_and_build_questions(self, **kwargs: object) -> object:
        raise AssertionError("factory must not be called for now FieldForm")


def test_issue_now_returns_field_form_url_without_factory_or_registry() -> None:
    """happy: FieldForm URL prefix+path+token; Drive factory/registry unused."""
    registry = InMemoryMicromarketInventoryFormRegistry()
    uc = _issue_uc(registry=registry, factory=_RaisingFactory())
    pages = _pages("2311", "2312")

    result = uc.execute(
        machine_code="701",
        mode="now",
        pages=pages,
        technician_id=_TECH,
    )

    assert isinstance(result, IssuedMicromarketInventoryLink)
    parsed = urlparse(result.form_url)
    assert f"{parsed.scheme}://{parsed.netloc}" == _FIELD_BASE
    assert parsed.path == "/forms/micromarket-inventory/now"
    token = parse_qs(parsed.query)["token"][0]
    payload = verify_micromarket_inventory_form_token(
        token,
        "now-secret",
        expected_purpose="micromarket_inventory_now",
    )
    assert payload.product_codes == ("2311", "2312")
    assert payload.machine_code == "701"
    assert registry.get("701", "now", result.fingerprint_id) is None


def test_issue_now_computes_fingerprint_without_registry_put() -> None:
    """edge: fingerprint_id may be set for log; registry put is not called."""
    registry = InMemoryMicromarketInventoryFormRegistry()
    uc = _issue_uc(registry=registry, factory=_RaisingFactory())
    result = uc.execute(
        machine_code="701",
        mode="now",
        pages=_pages("d-1"),
        technician_id=_TECH,
    )
    assert isinstance(result, IssuedMicromarketInventoryLink)
    assert result.fingerprint_id
    assert registry.get("701", "now", result.fingerprint_id) is None


def test_issue_token_product_codes_follow_page_flatten_order() -> None:
    """happy: token codes == flatten pages (not alphabetical sort)."""
    uc = _issue_uc(factory=_RaisingFactory())
    pages = (
        InventoryFormPage(kit_group_id=20, product_codes=("d-9",), title="B"),
        InventoryFormPage(kit_group_id=10, product_codes=("d-1", "d-2"), title="A"),
    )
    result = uc.execute(
        machine_code="701",
        mode="now",
        pages=pages,
        technician_id=_TECH,
    )
    assert isinstance(result, IssuedMicromarketInventoryLink)
    token = parse_qs(urlparse(result.form_url).query)["token"][0]
    payload = verify_micromarket_inventory_form_token(
        token,
        "now-secret",
        expected_purpose="micromarket_inventory_now",
    )
    assert payload.product_codes == ("d-9", "d-1", "d-2")


def test_issue_link_empty_sku_set_returns_user_message() -> None:
    uc = _issue_uc(factory=_RaisingFactory())
    result = uc.execute(
        machine_code="701",
        mode="now",
        pages=(),
        technician_id=_TECH,
    )
    assert isinstance(result, EmptyMicromarketSkuSet)
    assert "SKU" in result.message


def test_issue_now_raises_when_base_url_missing() -> None:
    settings = MicromarketLoadingSettings.model_construct(
        field_forms_public_base_url="",
        inventory_form_now_token_secret=SecretStr("now-secret"),
    )
    uc = _issue_uc(
        field_forms_public_base_url="",
        forms_settings=settings,
        factory=_RaisingFactory(),
    )
    with pytest.raises(ValueError, match="FIELD_FORMS_PUBLIC_BASE_URL"):
        uc.execute(
            machine_code="701",
            mode="now",
            pages=_pages("d-1"),
            technician_id=_TECH,
        )


def test_form_registry_hit_reuses_form_id_for_as_of() -> None:
    """as_of Google Forms path still reuses registry hit."""
    registry = InMemoryMicromarketInventoryFormRegistry()
    factory = StubMicromarketInventoryFormFactory(
        form_id="mm-form-1", form_url="https://forms.example/1"
    )
    uc = _issue_uc(registry=registry, factory=factory)
    pages = _pages("2311", "2312")

    first = uc.execute(
        machine_code="701",
        mode="as_of",
        pages=pages,
        technician_id=_TECH,
    )
    assert isinstance(first, IssuedMicromarketInventoryLink)
    assert first.form_id == "mm-form-1"

    factory.form_id = "mm-form-should-not-use"
    second = uc.execute(
        machine_code="701",
        mode="as_of",
        pages=pages,
        technician_id=_TECH,
    )
    assert isinstance(second, IssuedMicromarketInventoryLink)
    assert second.form_id == "mm-form-1"
    assert second.fingerprint_id == first.fingerprint_id
