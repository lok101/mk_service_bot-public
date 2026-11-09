from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_REVISION_PROFILE_ID,
    FormInventoryPolicyLine,
    MemoryFormInventoryPolicyStore,
    seed_coffee_ingredient_policies,
)
from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.application.form_submissions.coffee_field_form_accept import (
    AcceptCoffeeLoadingFieldForm,
    AcceptCoffeeRevisionFieldForm,
)
from src.application.product_identity.models import DomainProduct
from src.domain.form_tokens import CoffeeFormTokenPayload, create_coffee_form_token
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.models import RevisionSource
from src.domain.product_catalog import ProductUnit
from src.infrastructure.field_forms import CoffeeDomainIngredientProductCodeResolver
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.interfaces.field_forms.coffee_forms import (
    CoffeeFieldFormDeps,
    register_coffee_field_form_routes,
)

_SECRET = "coffee-radio-secret"
_TECH = TechnicianId("tech-1")
_MACHINE = MachineId("101")
_ISSUED_AT = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
_LOADING_PATH = "/forms/coffee-loading"
_REVISION_PATH = "/forms/coffee-revision"


@dataclass
class _MemoryProducts:
    products: tuple[DomainProduct, ...] = ()

    def list_visible(self) -> tuple[DomainProduct, ...]:
        return tuple(p for p in self.products if not p.hidden)

    def get_by_number(self, number: str) -> DomainProduct | None:
        for product in self.products:
            if product.number == number:
                return product
        return None

    def get(self, domain_product_id: str) -> DomainProduct | None:
        for product in self.products:
            if product.domain_product_id == domain_product_id:
                return product
        return None

    def get_by_catalog_code(self, catalog_code: str) -> DomainProduct | None:
        for product in self.products:
            if product.catalog_code == catalog_code:
                return product
        return None

    def insert(self, product: DomainProduct) -> None:
        del product

    def save(self, product: DomainProduct) -> None:
        del product

    def numbers(self) -> tuple[str, ...]:
        return tuple(p.number for p in self.products)


@dataclass
class _RegisterRevision:
    def execute(self, command: object) -> RevisionCompleted:
        del command
        return RevisionCompleted(
            event_id=EventId("rev-event-1"),
            revision_id=RevisionId("rev-1"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=_SUBMITTED_AT,
            occurred_at=_SUBMITTED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="coffee-revision-field-form",
            form_token="tok",
        )


@dataclass
class _RegisterLoading:
    def execute(self, command: object) -> LoadingSubmitted:
        del command
        return LoadingSubmitted(
            event_id=EventId("load-event-1"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            submitted_at=_SUBMITTED_AT,
            occurred_at=_SUBMITTED_AT,
            form_id="coffee-loading-field-form",
            form_token="tok",
        )


def _ingredient(number: str, name: str) -> DomainProduct:
    return DomainProduct(
        domain_product_id=f"id-{number}",
        number=number,
        name=name,
        catalog_code="ms-milk",
        hidden=False,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )


def _policies(
    *,
    domain_number: str = "d-1",
    radio_n: int | None = 5,
) -> MemoryFormInventoryPolicyStore:
    store = MemoryFormInventoryPolicyStore()
    seed_coffee_ingredient_policies(
        store,
        domain_number=domain_number,
        loading=FormInventoryPolicyLine(
            domain_number=domain_number,
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
            radio_n=radio_n if radio_n is not None else 10,
        ),
        revision=FormInventoryPolicyLine(
            domain_number=domain_number,
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
        ),
        warehouse=FormInventoryPolicyLine(
            domain_number=domain_number,
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
        ),
    )
    if radio_n is None:
        line = store.get_line(COFFEE_LOADING_PROFILE_ID, domain_number)
        assert line is not None
        store.upsert_line(
            COFFEE_LOADING_PROFILE_ID,
            FormInventoryPolicyLine(
                domain_number=line.domain_number,
                min_qty=line.min_qty,
                max_qty=line.max_qty,
                radio_n=None,
            ),
        )
    return store


def _token(*, purpose: str, codes: tuple[str, ...] = ("d-1",)) -> str:
    return create_coffee_form_token(
        CoffeeFormTokenPayload(
            purpose=purpose,  # type: ignore[arg-type]
            technician_id=_TECH,
            machine_id=_MACHINE,
            product_codes=codes,
            issued_at=_ISSUED_AT,
            nonce="n-radio-1",
        ),
        _SECRET,
    )


def _client(
    *,
    policies: MemoryFormInventoryPolicyStore | None = None,
) -> tuple[TestClient, InMemoryFormSubmissionStore]:
    products = _MemoryProducts(products=(_ingredient("d-1", "Молоко"),))
    policy_store = policies if policies is not None else _policies()
    loading_resolver = CoffeeDomainIngredientProductCodeResolver(
        products=products,
        policies=policy_store,
        profile_id=COFFEE_LOADING_PROFILE_ID,
    )
    revision_resolver = CoffeeDomainIngredientProductCodeResolver(
        products=products,
        policies=policy_store,
        profile_id=COFFEE_REVISION_PROFILE_ID,
    )
    store = InMemoryFormSubmissionStore()
    loading_profile = policy_store.get_profile(COFFEE_LOADING_PROFILE_ID)
    revision_profile = policy_store.get_profile(COFFEE_REVISION_PROFILE_ID)
    assert loading_profile is not None and revision_profile is not None
    accept_revision = AcceptCoffeeRevisionFieldForm(
        accept_revision=AcceptRevisionFormSubmissionService(
            form_submission_store=store,
            register_revision_from_form=_RegisterRevision(),  # type: ignore[arg-type]
            product_code_resolver=revision_resolver,
            form_token_field_name="token",
            quantity_mode=revision_profile.input_mode,
            allow_empty=revision_profile.allow_empty,
            apply_stock_range=revision_profile.apply_stock_range,
            allow_zero=revision_profile.allow_zero,
        ),
    )
    accept_loading = AcceptCoffeeLoadingFieldForm(
        accept_loading=AcceptInventoryFormSubmissionService(
            form_submission_store=store,
            register_loading_from_form=_RegisterLoading(),  # type: ignore[arg-type]
            product_code_resolver=loading_resolver,
            form_token_field_name="token",
            quantity_mode=loading_profile.input_mode,
            allow_empty=loading_profile.allow_empty,
            apply_stock_range=loading_profile.apply_stock_range,
            allow_zero=loading_profile.allow_zero,
        ),
    )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=99,
            accept_revision=accept_revision,
            accept_loading=accept_loading,
            products=products,
            policies=policy_store,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    return TestClient(app), store


def test_loading_get_renders_quiet_scale() -> None:
    """happy: GET loading shows quiet scale 1…radio_n + zero aside, no Пусто."""
    client, _store = _client(policies=_policies(radio_n=5))
    token = _token(purpose="loading")
    response = client.get(_LOADING_PATH, params={"token": token})
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache"
    body = response.text
    assert 'name="qty_d-1"' in body
    assert 'type="radio"' in body
    assert 'value="0"' in body
    assert 'value="1"' in body
    assert 'value="5"' in body
    assert "field-form__line--tile" in body
    assert "field-form__scale-zero" in body
    assert "field-form__scale-item" in body
    assert "/forms/static/field_form.css?v=" in body
    assert "/forms/static/coffee_loading_radio.js?v=" in body
    assert "Пусто" not in body
    assert "data-qty-input" not in body
    assert 'type="text"' not in body


def test_loading_get_quiet_scale_chunks_rows() -> None:
    """edge: radio_n=12 → second scale-row for 11…12; zero still present."""
    client, _store = _client(policies=_policies(radio_n=12))
    token = _token(purpose="loading")
    response = client.get(_LOADING_PATH, params={"token": token})
    assert response.status_code == 200
    body = response.text
    assert body.count("field-form__scale-row") >= 2
    assert 'value="10"' in body
    assert 'value="11"' in body
    assert 'value="12"' in body
    assert 'value="0"' in body
    assert "field-form__scale-zero" in body


def test_loading_get_missing_radio_n_fails() -> None:
    """error: missing radio_n on loading line → GET fails."""
    client, _store = _client(policies=_policies(radio_n=None))
    token = _token(purpose="loading")
    response = client.get(_LOADING_PATH, params={"token": token})
    assert response.status_code == 422
    lowered = response.text.lower()
    assert "radio" in lowered or "радио" in lowered or "упаков" in lowered


def test_revision_get_no_radios() -> None:
    """edge: revision stays text input without radios."""
    client, _store = _client()
    token = _token(purpose="revision")
    response = client.get(_REVISION_PATH, params={"token": token})
    assert response.status_code == 200
    body = response.text
    assert 'type="radio"' not in body
    assert 'name="qty_d-1"' in body
    assert 'type="text"' in body


def test_loading_post_zero_accepted() -> None:
    """happy: POST selected 0 packages → Accept."""
    client, store = _client(policies=_policies(radio_n=5))
    token = _token(purpose="loading")
    response = client.post(_LOADING_PATH, data={"token": token, "qty_d-1": "0"})
    assert response.status_code == 200
    assert "Принято" in response.text
    snapshot = store.get_by_form_token(token, "loading")
    assert snapshot is not None
    assert snapshot.validated_lines[0].quantity == Decimal("0")


def test_loading_post_missing_selection_422() -> None:
    """error: empty qty on loading → 422 without Accept."""
    client, store = _client(policies=_policies(radio_n=5))
    token = _token(purpose="loading")
    response = client.post(_LOADING_PATH, data={"token": token, "qty_d-1": ""})
    assert response.status_code == 422
    assert store.get_by_form_token(token, "loading") is None
