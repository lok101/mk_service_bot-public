from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.form_inventory_policy import (
    TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
    FormInventoryPolicyLine,
    MemoryFormInventoryPolicyStore,
    seed_coffee_ingredient_policies,
    upsert_policy_line,
)
from src.application.form_submissions import FormSubmissionValidationError
from src.application.product_identity.models import DomainProduct
from src.domain.form_tokens import (
    TechnicianWarehouseInventoryTokenPayload,
    create_technician_warehouse_inventory_token,
)
from src.domain.ids import TechnicianId
from src.domain.product_catalog import ProductUnit
from src.interfaces.field_forms.technician_warehouse_inventory import (
    TechnicianWarehouseInventoryFieldFormDeps,
    register_technician_warehouse_inventory_field_form_routes,
)

_SECRET = "warehouse-field-secret"
_TECH = TechnicianId("tech-1")
_ISSUED_AT = datetime.now(tz=UTC) - timedelta(hours=1)
_SUBMITTED_AT = datetime.now(tz=UTC)
_PATH = "/forms/technician-warehouse-inventory"


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
class _RecordingErrorNotifier:
    calls: list[tuple[TechnicianId, str]] = field(default_factory=list)

    async def notify(self, *, technician_id: TechnicianId, reason: str) -> None:
        self.calls.append((technician_id, reason))


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
        del catalog_code
        return None

    def insert(self, product: DomainProduct) -> None:
        del product

    def save(self, product: DomainProduct) -> None:
        del product

    def numbers(self) -> tuple[str, ...]:
        return tuple(p.number for p in self.products)


def _ingredient(number: str, name: str) -> DomainProduct:
    return DomainProduct(
        domain_product_id=f"id-{number}",
        number=number,
        name=name,
        catalog_code="MS-1",
        hidden=False,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )


def _token() -> str:
    return create_technician_warehouse_inventory_token(
        TechnicianWarehouseInventoryTokenPayload(
            technician_id=_TECH,
            issued_at=_ISSUED_AT,
            nonce="n1",
        ),
        _SECRET,
    )


def _client(
    *,
    accept: _RecordingAccept | None = None,
    products: _MemoryProducts | None = None,
    error_notifier: _RecordingErrorNotifier | None = None,
) -> tuple[TestClient, _RecordingAccept, _RecordingErrorNotifier]:
    accept = accept or _RecordingAccept()
    error_notifier = error_notifier or _RecordingErrorNotifier()
    products = products or _MemoryProducts(
        (
            _ingredient("d-1", "Молоко"),
            _ingredient("d-2", "Зерно"),
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
                max_qty=Decimal("99"),
                radio_n=5,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
            ),
        )
    app = FastAPI()
    register_technician_warehouse_inventory_field_form_routes(
        app,
        TechnicianWarehouseInventoryFieldFormDeps(
            token_secret=_SECRET,
            qty_max=99,
            accept=accept,
            products=products,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
            token_max_age_hours=24.0,
            error_notifier=error_notifier,
        ),
    )
    return TestClient(app), accept, error_notifier


def test_get_requires_all_lines_for_submit_gate() -> None:
    """happy: GET lists visible ingredients, Пусто, and field_form.js."""
    client, _, _ = _client()
    response = client.get(_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert "Молоко" in body
    assert "Зерно" in body
    assert 'data-require-all-lines="1"' in body
    assert "field_form.js" in body
    assert "inventory_qty_parse.js" in body
    assert 'data-min="0"' in body
    assert 'data-max="99"' in body
    assert 'data-integer="1"' in body
    assert "Пусто" in body
    assert "data-empty-toggle" in body


def test_warehouse_orders_and_labels_from_policy() -> None:
    """happy: order + form_label/hint from warehouse policy lines."""
    accept = _RecordingAccept()
    products = _MemoryProducts(
        (
            _ingredient("d-1", "Молоко сухое 1 кг"),
            _ingredient("d-2", "Кофе зерно Arabica"),
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
                max_qty=Decimal("99"),
                radio_n=5,
                sort_order=sort_order,
                form_label=label,
                form_hint=hint,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
                sort_order=sort_order,
                form_label=label,
                form_hint=hint,
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
                sort_order=sort_order,
                form_label=label,
                form_hint=hint,
            ),
        )
    app = FastAPI()
    register_technician_warehouse_inventory_field_form_routes(
        app,
        TechnicianWarehouseInventoryFieldFormDeps(
            token_secret=_SECRET,
            qty_max=99,
            accept=accept,
            products=products,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
            token_max_age_hours=24.0,
        ),
    )
    client = TestClient(app)
    response = client.get(_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert body.index("Кофе") < body.index("Молоко сухое 1 кг")
    assert "верхний бункер" in body
    assert "field-form__hint" in body
    assert "Кофе зерно Arabica" not in body

    upsert_policy_line(
        policies,
        profile_id=TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
        domain_number="d-2",
        min_qty=Decimal("0"),
        max_qty=Decimal("99"),
        sort_order=1,
        form_label="",
        form_hint="",
    )
    empty_hint = client.get(_PATH, params={"token": _token()})
    assert empty_hint.status_code == 200
    assert "Кофе зерно Arabica" in empty_hint.text
    assert "field-form__hint" not in empty_hint.text
    assert "верхний бункер" not in empty_hint.text


def test_post_over_max_error_uses_ingredient_name() -> None:
    """error: qty > max mentions product name, not only domain code."""
    client, accept, notifier = _client()
    response = client.post(
        _PATH,
        data={"token": _token(), "qty_d-1": "100", "qty_d-2": "1"},
    )
    assert response.status_code == 422
    assert accept.calls == 0
    assert "Количество не должно превышать 99 для Молоко" in response.text
    assert notifier.calls == []


def test_warehouse_field_form_post_accepts_domain_keys() -> None:
    """happy: POST all lines including 0 → Accept with domain titles."""
    client, accept, notifier = _client()
    response = client.post(
        _PATH,
        data={"token": _token(), "qty_d-1": "0", "qty_d-2": "3"},
    )
    assert response.status_code == 200
    assert "Принято" in response.text
    assert accept.calls == 1
    assert notifier.calls == []
    answers = accept.last_kwargs["answers"]
    assert isinstance(answers, tuple)
    titles = {answer.title: answer.value for answer in answers}
    assert titles == {"d-1": "0", "d-2": "3"}


def test_post_empty_line_422() -> None:
    """error: missing/empty qty → 422 without Accept; no chat notify."""
    client, accept, notifier = _client()
    response = client.post(
        _PATH,
        data={"token": _token(), "qty_d-1": "2", "qty_d-2": ""},
    )
    assert response.status_code == 422
    assert accept.calls == 0
    assert "Нужен ответ" in response.text
    assert "Зерно" in response.text
    assert notifier.calls == []


def test_post_validation_error_from_accept() -> None:
    """error: Accept validation → 422 in form; no chat notify."""
    accept = _RecordingAccept(error=FormSubmissionValidationError("pack missing"))
    client, _, notifier = _client(accept=accept)
    response = client.post(
        _PATH,
        data={"token": _token(), "qty_d-1": "1", "qty_d-2": "1"},
    )
    assert response.status_code == 422
    assert "pack missing" in response.text
    assert notifier.calls == []


def test_post_concurrency_error_409_no_chat_notify() -> None:
    """error: warehouse concurrency → 409 in form; no chat notify."""
    from src.domain.technician_warehouse.errors import TechnicianWarehouseConcurrencyError

    accept = _RecordingAccept(
        error=TechnicianWarehouseConcurrencyError(technician_id=_TECH),
    )
    client, _, notifier = _client(accept=accept)
    response = client.post(
        _PATH,
        data={"token": _token(), "qty_d-1": "1", "qty_d-2": "1"},
    )
    assert response.status_code == 409
    assert _TECH.value in response.text
    assert notifier.calls == []
