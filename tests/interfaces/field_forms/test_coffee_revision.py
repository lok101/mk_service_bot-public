from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.form_inventory_policy import (
    COFFEE_REVISION_PROFILE_ID,
    FormInventoryPolicyLine,
    MemoryFormInventoryPolicyStore,
    seed_coffee_ingredient_policies,
    upsert_policy_line,
)
from src.application.product_identity.models import DomainProduct
from src.domain.form_tokens import (
    CoffeeFormTokenPayload,
    create_coffee_form_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.field_forms.coffee_forms import (
    CoffeeFieldFormDeps,
    register_coffee_field_form_routes,
)

_SECRET = "coffee-revision-field-secret"
_TECH = TechnicianId("tech-1")
_MACHINE = MachineId("101")
_ISSUED_AT = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
_REVISION_PATH = "/forms/coffee-revision"
_LOADING_PATH = "/forms/coffee-loading"


@dataclass
class _RecordingAccept:
    calls: int = 0
    last_kwargs: dict[str, object] = field(default_factory=dict)
    error: Exception | None = None

    def execute(self, **kwargs: object) -> object:
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        if self.error is not None:
            raise self.error
        return object()


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


def _ingredient(
    *,
    number: str,
    name: str,
    hidden: bool = False,
    catalog_code: str | None = "MS-1",
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=f"id-{number}",
        number=number,
        name=name,
        catalog_code=catalog_code,
        hidden=hidden,
        kind="coffee_ingredient",
    )


def _token(
    *,
    purpose: str = "revision",
    codes: tuple[str, ...] = ("d-1", "d-2"),
    secret: str = _SECRET,
) -> str:
    return create_coffee_form_token(
        CoffeeFormTokenPayload(
            purpose=purpose,  # type: ignore[arg-type]
            technician_id=_TECH,
            machine_id=_MACHINE,
            product_codes=codes,
            issued_at=_ISSUED_AT,
            nonce="n-coffee-1",
        ),
        secret,
    )


def _client(
    *,
    accept_revision: _RecordingAccept | None = None,
    accept_loading: _RecordingAccept | None = None,
    products: _MemoryProducts | None = None,
    qty_max: int = 99,
    token_max_age_hours: float | None = None,
) -> tuple[TestClient, _RecordingAccept, _RecordingAccept]:
    revision_accept = accept_revision or _RecordingAccept()
    loading_accept = accept_loading or _RecordingAccept()
    store = products or _MemoryProducts(
        products=(
            _ingredient(number="d-1", name="Молоко"),
            _ingredient(number="d-2", name="Кофе зерно"),
            _ingredient(number="d-hidden", name="Скрытый", hidden=True),
        ),
    )
    policies = MemoryFormInventoryPolicyStore()
    for number in ("d-1", "d-2", "d-hidden"):
        seed_coffee_ingredient_policies(
            policies,
            domain_number=number,
            loading=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100000"),
                radio_n=5,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100000"),
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100000"),
            ),
        )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=qty_max,
            accept_revision=revision_accept,
            accept_loading=loading_accept,
            products=store,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
            token_max_age_hours=token_max_age_hours,
        ),
    )
    return TestClient(app), revision_accept, loading_accept


def test_coffee_revision_get_lists_visible_ingredients() -> None:
    """happy: GET HTML lists visible coffee_ingredient names + qty inputs."""
    client, _rev, _load = _client()
    response = client.get(_REVISION_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert "Молоко" in body
    assert "Кофе зерно" in body
    assert 'name="qty_d-1"' in body
    assert 'name="qty_d-2"' in body
    assert "Скрытый" not in body
    assert 'name="qty_d-hidden"' not in body
    assert "viewport" in body.lower()
    assert "field-form" in body
    assert "admin-sidebar" not in body


def test_coffee_form_rejects_bad_token() -> None:
    """error: bad/wrong-purpose token → 4xx without Accept."""
    client, rev, load = _client()
    bad = client.get(_REVISION_PATH, params={"token": "not-a-token"})
    assert bad.status_code == 422
    assert rev.calls == 0

    wrong = client.get(
        _REVISION_PATH,
        params={"token": _token(purpose="loading")},
    )
    assert wrong.status_code == 422
    assert rev.calls == 0
    assert load.calls == 0


def test_coffee_form_hides_hidden_ingredient() -> None:
    """edge: hidden ingredient never rendered even if sneaked into token."""
    client, _rev, _load = _client()
    response = client.get(
        _REVISION_PATH,
        params={"token": _token(codes=("d-1", "d-hidden"))},
    )
    assert response.status_code == 200
    body = response.text
    assert "Молоко" in body
    assert "Скрытый" not in body
    assert 'name="qty_d-hidden"' not in body


def test_coffee_revision_orders_and_labels_from_policy() -> None:
    """happy: FieldForm order + form_label/hint from revision policy lines."""
    revision_accept = _RecordingAccept()
    loading_accept = _RecordingAccept()
    store = _MemoryProducts(
        products=(
            _ingredient(number="d-1", name="Молоко сухое 1 кг"),
            _ingredient(number="d-2", name="Кофе зерно Arabica"),
        ),
    )
    policies = MemoryFormInventoryPolicyStore()
    for number, sort_order, label, hint in (
        ("d-1", 2, "", ""),
        ("d-2", 1, "Кофе", "верхний бункер"),
    ):
        seed_coffee_ingredient_policies(
            policies,
            domain_number=number,
            loading=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100000"),
                radio_n=5,
                sort_order=sort_order,
                form_label=label,
                form_hint=hint,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100000"),
                sort_order=sort_order,
                form_label=label,
                form_hint=hint,
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100000"),
                sort_order=sort_order,
                form_label=label,
                form_hint=hint,
            ),
        )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=99,
            accept_revision=revision_accept,
            accept_loading=loading_accept,
            products=store,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    client = TestClient(app)
    response = client.get(
        _REVISION_PATH,
        params={"token": _token(codes=("d-1", "d-2"))},
    )
    assert response.status_code == 200
    body = response.text
    coffee_pos = body.index("Кофе")
    milk_pos = body.index("Молоко сухое 1 кг")
    assert coffee_pos < milk_pos
    assert "верхний бункер" in body
    assert "field-form__hint" in body
    assert "Кофе зерно Arabica" not in body

    upsert_policy_line(
        policies,
        profile_id=COFFEE_REVISION_PROFILE_ID,
        domain_number="d-2",
        min_qty=Decimal("0"),
        max_qty=Decimal("100000"),
        sort_order=1,
        form_label="",
        form_hint="",
    )
    empty_hint = client.get(
        _REVISION_PATH,
        params={"token": _token(codes=("d-2",))},
    )
    assert empty_hint.status_code == 200
    assert "Кофе зерно Arabica" in empty_hint.text
    assert "field-form__hint" not in empty_hint.text
    assert "верхний бункер" not in empty_hint.text


def test_revision_empty_toggle_script_present() -> None:
    """happy: revision text UI includes Пусто control and field_form.js."""
    client, _rev, _load = _client()
    response = client.get(_REVISION_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert "Пусто" in body
    assert "data-empty-toggle" in body
    assert "field_form.js" in body
    assert 'id="field-form-coffee"' in body or 'id="field-form-inventory"' in body


def test_revision_post_over_env_under_policy_ok() -> None:
    """happy: qty above env 99 accepted when coffee_revision policy max allows."""
    client, rev, _load = _client(qty_max=99)
    token = _token()
    response = client.post(
        _REVISION_PATH,
        data={"token": token, "qty_d-1": "500", "qty_d-2": "0"},
    )
    assert response.status_code == 200
    assert rev.calls == 1
    assert "Принято" in response.text


def test_revision_error_uses_ingredient_name() -> None:
    """error: over policy max names the ingredient, not only d-… code."""
    revision_accept = _RecordingAccept()
    loading_accept = _RecordingAccept()
    products = _MemoryProducts(
        products=(
            _ingredient(number="d-1", name="Сливки"),
            _ingredient(number="d-2", name="Кофе"),
        ),
    )
    policies = MemoryFormInventoryPolicyStore()
    for number in ("d-1", "d-2"):
        seed_coffee_ingredient_policies(
            policies,
            domain_number=number,
            loading=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100"),
                radio_n=5,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100"),
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("100"),
            ),
        )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=99,
            accept_revision=revision_accept,
            accept_loading=loading_accept,
            products=products,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    client = TestClient(app)
    response = client.post(
        _REVISION_PATH,
        data={"token": _token(), "qty_d-1": "101", "qty_d-2": "0"},
    )
    assert response.status_code == 422
    assert revision_accept.calls == 0
    assert "Сливки" in response.text
    assert "не должно превышать 100" in response.text


def test_revision_missing_policy_422() -> None:
    """error: visible ingredient without coffee_revision policy line → 422."""
    revision_accept = _RecordingAccept()
    loading_accept = _RecordingAccept()
    products = _MemoryProducts(
        products=(
            _ingredient(number="d-1", name="Молоко"),
            _ingredient(number="d-2", name="Кофе зерно"),
        ),
    )
    policies = MemoryFormInventoryPolicyStore()
    seed_coffee_ingredient_policies(
        policies,
        domain_number="d-2",
        loading=FormInventoryPolicyLine(
            domain_number="d-2",
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
            radio_n=5,
        ),
        revision=FormInventoryPolicyLine(
            domain_number="d-2",
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
        ),
        warehouse=FormInventoryPolicyLine(
            domain_number="d-2",
            min_qty=Decimal("0"),
            max_qty=Decimal("100000"),
        ),
    )
    # d-1 has no coffee_revision line
    upsert_policy_line(
        policies,
        profile_id=COFFEE_REVISION_PROFILE_ID,
        domain_number="d-2",
        min_qty=Decimal("0"),
        max_qty=Decimal("100000"),
    )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=99,
            accept_revision=revision_accept,
            accept_loading=loading_accept,
            products=products,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    client = TestClient(app)
    response = client.post(
        _REVISION_PATH,
        data={"token": _token(), "qty_d-1": "10", "qty_d-2": "0"},
    )
    assert response.status_code == 422
    assert revision_accept.calls == 0
