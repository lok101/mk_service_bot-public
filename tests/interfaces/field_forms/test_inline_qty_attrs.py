from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.interfaces.field_forms.test_coffee_revision import (
    _ingredient,
    _MemoryProducts,
    _RecordingAccept,
)

from src.application.form_inventory_policy import (
    FormInventoryPolicyLine,
    MemoryFormInventoryPolicyStore,
    seed_coffee_ingredient_policies,
)
from src.domain.form_tokens import CoffeeFormTokenPayload, create_coffee_form_token
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.field_forms.coffee_forms import (
    CoffeeFieldFormDeps,
    register_coffee_field_form_routes,
)

_SECRET = "test-secret-inline-qty"
_REVISION_PATH = "/forms/coffee-revision"
_ISSUED_AT = datetime(2026, 11, 6, 11, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _token() -> str:
    return create_coffee_form_token(
        CoffeeFormTokenPayload(
            purpose="revision",
            technician_id=TechnicianId("t-1"),
            machine_id=MachineId("m-1"),
            product_codes=("d-1",),
            issued_at=_ISSUED_AT,
            nonce="n-inline-1",
        ),
        _SECRET,
    )


def test_revision_get_emits_qty_field_rule_attrs() -> None:
    """happy: revision GET projects policy min/max as data-* on text qty."""
    products = _MemoryProducts(products=(_ingredient(number="d-1", name="Сливки"),))
    policies = MemoryFormInventoryPolicyStore()
    seed_coffee_ingredient_policies(
        policies,
        domain_number="d-1",
        loading=FormInventoryPolicyLine(
            domain_number="d-1",
            min_qty=Decimal("0"),
            max_qty=Decimal("20"),
            radio_n=5,
        ),
        revision=FormInventoryPolicyLine(
            domain_number="d-1",
            min_qty=Decimal("0"),
            max_qty=Decimal("500"),
        ),
        warehouse=FormInventoryPolicyLine(
            domain_number="d-1",
            min_qty=Decimal("0"),
            max_qty=Decimal("99"),
        ),
    )
    app = FastAPI()
    register_coffee_field_form_routes(
        app,
        CoffeeFieldFormDeps(
            revision_token_secret=_SECRET,
            loading_token_secret=_SECRET,
            qty_max=99,
            accept_revision=_RecordingAccept(),
            accept_loading=_RecordingAccept(),
            products=products,
            policies=policies,
            clock=lambda: _SUBMITTED_AT,
        ),
    )
    client = TestClient(app)
    body = client.get(_REVISION_PATH, params={"token": _token()}).text
    assert 'name="qty_d-1"' in body
    assert 'data-min="0"' in body
    assert 'data-max="500"' in body
    assert 'data-required="1"' in body
    assert "data-integer" not in body
    assert "data-field-error" in body
    assert "inventory_qty_parse.js" in body
    assert "field_form.js" in body
