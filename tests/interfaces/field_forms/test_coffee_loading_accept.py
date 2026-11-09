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

_SECRET = "coffee-accept-secret"
_TECH = TechnicianId("tech-1")
_MACHINE = MachineId("101")
_ISSUED_AT = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
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


def _ingredient(
    number: str,
    name: str,
    *,
    catalog_code: str = "ms-milk",
    pack_size: Decimal = Decimal("1000"),
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=f"id-{number}",
        number=number,
        name=name,
        catalog_code=catalog_code,
        hidden=False,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=pack_size,
    )


def _policies(*, domain_number: str = "d-1") -> MemoryFormInventoryPolicyStore:
    store = MemoryFormInventoryPolicyStore()
    seed_coffee_ingredient_policies(
        store,
        domain_number=domain_number,
        loading=FormInventoryPolicyLine(
            domain_number=domain_number,
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
            radio_n=10,
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
    return store


def _token(*, purpose: str, codes: tuple[str, ...] = ("d-1",)) -> str:
    return create_coffee_form_token(
        CoffeeFormTokenPayload(
            purpose=purpose,  # type: ignore[arg-type]
            technician_id=_TECH,
            machine_id=_MACHINE,
            product_codes=codes,
            issued_at=_ISSUED_AT,
            nonce="n-accept-1",
        ),
        _SECRET,
    )


def _client() -> tuple[TestClient, InMemoryFormSubmissionStore]:
    products = _MemoryProducts(products=(_ingredient("d-1", "Молоко"),))
    policies = _policies()
    loading_resolver = CoffeeDomainIngredientProductCodeResolver(
        products=products,
        policies=policies,
        profile_id=COFFEE_LOADING_PROFILE_ID,
    )
    revision_resolver = CoffeeDomainIngredientProductCodeResolver(
        products=products,
        policies=policies,
        profile_id=COFFEE_REVISION_PROFILE_ID,
    )
    store = InMemoryFormSubmissionStore()
    loading_profile = policies.get_profile(COFFEE_LOADING_PROFILE_ID)
    revision_profile = policies.get_profile(COFFEE_REVISION_PROFILE_ID)
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
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    return TestClient(app), store


def test_accept_loading_uses_domain_pack_size() -> None:
    """happy: POST qty → Accept; pack_size from domain product, not Sheets."""
    client, store = _client()
    token = _token(purpose="loading")
    response = client.post(
        _LOADING_PATH,
        data={"token": token, "qty_d-1": "2"},
    )
    assert response.status_code == 200
    assert "Принято" in response.text
    snapshot = store.get_by_form_token(token, "loading")
    assert snapshot is not None
    assert snapshot.status == "accepted"
    assert len(snapshot.validated_lines) == 1
    line = snapshot.validated_lines[0]
    assert line.product_spec.product_code == "d-1"
    assert line.product_spec.pack_size == Decimal("1000")
    assert line.quantity == Decimal("2")


def test_accept_without_policy_fails() -> None:
    """error: missing policy line → resolve fails → 422."""
    products = _MemoryProducts(products=(_ingredient("d-1", "Молоко"),))
    policies = MemoryFormInventoryPolicyStore()
    resolver = CoffeeDomainIngredientProductCodeResolver(
        products=products,
        policies=policies,
        profile_id=COFFEE_LOADING_PROFILE_ID,
    )
    store = InMemoryFormSubmissionStore()
    accept_loading = AcceptCoffeeLoadingFieldForm(
        accept_loading=AcceptInventoryFormSubmissionService(
            form_submission_store=store,
            register_loading_from_form=_RegisterLoading(),  # type: ignore[arg-type]
            product_code_resolver=resolver,
            form_token_field_name="token",
        ),
    )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=99,
            accept_revision=AcceptCoffeeRevisionFieldForm(
                accept_revision=AcceptRevisionFormSubmissionService(
                    form_submission_store=store,
                    register_revision_from_form=_RegisterRevision(),  # type: ignore[arg-type]
                    product_code_resolver=resolver,
                    form_token_field_name="token",
                ),
            ),
            accept_loading=accept_loading,
            products=products,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    client = TestClient(app)
    token = _token(purpose="loading")
    response = client.post(_LOADING_PATH, data={"token": token, "qty_d-1": "1"})
    assert response.status_code == 422
    assert store.get_by_form_token(token, "loading") is None


def test_coffee_post_unknown_number_422() -> None:
    """error: unknown / hidden code in POST → 422 without Accept."""
    client, store = _client()
    token = _token(purpose="loading")
    response = client.post(
        _LOADING_PATH,
        data={"token": token, "qty_d-1": "1", "qty_d-unknown": "3"},
    )
    assert response.status_code == 422
    assert store.get_by_form_token(token, "loading") is None


def test_qty_loading_packages_vs_revision_base() -> None:
    """edge: loading keeps package qty; revision accepts base units."""
    client, store = _client()
    loading_token = _token(purpose="loading")
    loading = client.post(
        _LOADING_PATH,
        data={"token": loading_token, "qty_d-1": "3"},
    )
    assert loading.status_code == 200
    loading_snap = store.get_by_form_token(loading_token, "loading")
    assert loading_snap is not None
    assert loading_snap.validated_lines[0].quantity == Decimal("3")

    revision_token = _token(purpose="revision")
    revision = client.post(
        _REVISION_PATH,
        data={"token": revision_token, "qty_d-1": "50"},
    )
    assert revision.status_code == 200
    revision_snap = store.get_by_form_token(revision_token, "revision")
    assert revision_snap is not None
    assert revision_snap.validated_lines[0].quantity == Decimal("50")
    assert revision_snap.validated_lines[0].product_spec.product_code == "d-1"


def test_domain_resolver_uses_domain_pack_not_catalog() -> None:
    products = _MemoryProducts(
        products=(_ingredient("d-9", "Сахар", catalog_code="ms-sugar", pack_size=Decimal("500")),)
    )
    policies = _policies(domain_number="d-9")
    resolver = CoffeeDomainIngredientProductCodeResolver(
        products=products,
        policies=policies,
        profile_id=COFFEE_LOADING_PROFILE_ID,
    )
    spec = resolver.resolve_by_name("d-9")
    assert spec.product_code == "d-9"
    assert spec.name == "Сахар"
    assert spec.pack_size == Decimal("500")
