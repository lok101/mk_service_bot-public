from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.micromarket_loading.accept_inventory import VisitFinalizedRecountRejected
from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.domain.form_tokens import (
    MicromarketInventoryFormTokenPayload,
    create_micromarket_inventory_form_token,
)
from src.domain.ids import EventId, TechnicianId
from src.domain.micromarket_loading.events import MicromarketInventoryAccepted
from src.interfaces.field_forms.micromarket_inventory_now import (
    MicromarketInventoryNowFieldFormDeps,
    register_micromarket_inventory_now_field_form_routes,
)

_SECRET = "mm-now-field-secret"
_TECH = TechnicianId("tech-1")
_MACHINE = "701"
_ISSUED_AT = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
_PATH = "/forms/micromarket-inventory/now"
_CSS = Path("src/interfaces/field_forms/static/field_form.css")
_TZ = ZoneInfo("Europe/Moscow")
_DAY_END = 6


@dataclass
class _RecordingAccept:
    calls: int = 0
    last_kwargs: dict[str, object] = field(default_factory=dict)
    error: Exception | None = None

    def execute(self, **kwargs: object) -> None:
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        if self.error is not None:
            raise self.error


@dataclass
class _FinalizedPort:
    finalized: bool = False

    def is_finalized(self, machine_code: str, checked_at: datetime) -> bool:
        del machine_code, checked_at
        return self.finalized


@dataclass
class _MemoryStockStore:
    events: list[object] = field(default_factory=list)

    def load(self, machine_code: str) -> object | None:
        del machine_code
        return None

    def save(self, stock: object) -> None:
        del stock

    def list_events(self, machine_code: str) -> list[object]:
        del machine_code
        return list(self.events)


def _token(
    *,
    codes: tuple[str, ...] = ("d-1", "d-2"),
    purpose: str = "micromarket_inventory_now",
) -> str:
    return create_micromarket_inventory_form_token(
        MicromarketInventoryFormTokenPayload(
            purpose=purpose,  # type: ignore[arg-type]
            technician_id=_TECH,
            machine_code=_MACHINE,
            fingerprint_id="fp-1",
            product_codes=codes,
            issued_at=_ISSUED_AT,
            nonce="n-field-1",
        ),
        _SECRET,
    )


def _pages_for_codes(codes: tuple[str, ...]) -> tuple[InventoryFormPage, ...]:
    return (
        InventoryFormPage(
            kit_group_id=10,
            product_codes=codes,
            title="Холод",
        ),
    )


def _inventory_event(
    *,
    quantities: tuple[tuple[str, Decimal], ...],
    as_of: datetime = _SUBMITTED_AT,
) -> MicromarketInventoryAccepted:
    return MicromarketInventoryAccepted(
        event_id=EventId("inv-event-1"),
        machine_code=_MACHINE,
        inventory_id="inv-1",
        as_of=as_of,
        quantities=quantities,
        occurred_at=as_of,
        partial=False,
    )


def _client(
    *,
    accept: _RecordingAccept | None = None,
    qty_max: int = 30,
    codes: tuple[str, ...] = ("d-1", "d-2"),
    token_max_age_hours: float | None = None,
    visit_finalized: _FinalizedPort | None = None,
    stock_store: _MemoryStockStore | None = None,
    max_body_bytes: int = 1_048_576,
) -> tuple[TestClient, _RecordingAccept]:
    acceptor = accept or _RecordingAccept()
    pages = _pages_for_codes(codes)
    app = FastAPI()
    register_micromarket_inventory_now_field_form_routes(
        app,
        MicromarketInventoryNowFieldFormDeps(
            now_token_secret=_SECRET,
            qty_max=qty_max,
            accept_micromarket_inventory=acceptor,
            load_pages=lambda _machine: pages,
            products=None,
            clock=lambda: _SUBMITTED_AT,
            token_max_age_hours=token_max_age_hours,
            visit_finalized=visit_finalized,
            stock_store=stock_store,
            timezone=_TZ,
            day_end_hour=_DAY_END,
            max_body_bytes=max_body_bytes,
        ),
    )
    return TestClient(app), acceptor


def test_get_valid_token_renders_shelf_titles_and_qty_inputs() -> None:
    """happy: GET HTML contains shelf titles + qty inputs."""
    client, _accept = _client()
    response = client.get(_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert "Холод" in body
    assert 'name="qty_d-1"' in body
    assert 'name="qty_d-2"' in body
    assert "field-form__code" not in body
    assert 'name="token"' in body
    assert "viewport" in body.lower()
    assert "admin-sidebar" not in body
    assert "field-form" in body


def test_get_after_now_prefills_last_inventory_qty() -> None:
    """happy: after now GET shows prefill qty from last inventory event."""
    store = _MemoryStockStore(
        events=[
            _inventory_event(quantities=(("d-1", Decimal("3")), ("d-2", Decimal("5")))),
        ],
    )
    client, _accept = _client(stock_store=store)
    response = client.get(_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert 'name="qty_d-1"\n            value="3"' in body or 'value="3"' in body
    assert 'value="5"' in body


def test_get_after_finalize_is_read_only_and_post_409() -> None:
    """happy: after finalize GET disabled + POST 409."""
    store = _MemoryStockStore(
        events=[_inventory_event(quantities=(("d-1", Decimal("2")),))],
    )
    finalized = _FinalizedPort(finalized=True)
    client, accept = _client(
        codes=("d-1",),
        stock_store=store,
        visit_finalized=finalized,
    )
    get_response = client.get(_PATH, params={"token": _token(codes=("d-1",))})
    assert get_response.status_code == 200
    assert "disabled" in get_response.text
    assert "визит завершён" in get_response.text.lower()
    assert "data-submit" not in get_response.text

    post_response = client.post(
        _PATH,
        data={"token": _token(codes=("d-1",)), "qty_d-1": "9"},
    )
    assert post_response.status_code == 409
    assert accept.calls == 0


def test_get_without_prior_inventory_leaves_inputs_unanswered() -> None:
    """edge: no prior inventory → unanswered empty values."""
    client, _accept = _client(stock_store=_MemoryStockStore())
    response = client.get(_PATH, params={"token": _token()})
    assert response.status_code == 200
    assert 'value=""' in response.text or "value=''" in response.text


def test_prefill_ignores_codes_not_in_pages() -> None:
    """edge: prefill ignores codes not in token/pages."""
    store = _MemoryStockStore(
        events=[
            _inventory_event(
                quantities=(
                    ("d-1", Decimal("4")),
                    ("extra", Decimal("99")),
                ),
            ),
        ],
    )
    client, _accept = _client(codes=("d-1",), stock_store=store)
    response = client.get(_PATH, params={"token": _token(codes=("d-1",))})
    assert response.status_code == 200
    assert 'value="4"' in response.text
    assert "extra" not in response.text
    assert "99" not in response.text


def test_post_valid_qty_calls_accept_in_zip_order() -> None:
    """happy: POST calls Accept with zip order of token product_codes."""
    client, accept = _client()
    token = _token(codes=("d-1", "d-2"))
    response = client.post(
        _PATH,
        data={"token": token, "qty_d-1": "3", "qty_d-2": "5"},
    )
    assert response.status_code == 200
    assert "принято" in response.text.lower()
    assert accept.calls == 1
    assert accept.last_kwargs["mode"] == "now"
    assert accept.last_kwargs["machine_code"] == _MACHINE
    assert accept.last_kwargs["quantities"] == {
        "d-1": Decimal("3"),
        "d-2": Decimal("5"),
    }
    assert accept.last_kwargs["submitted_at"] == _SUBMITTED_AT
    assert accept.last_kwargs["partial"] is False


def test_post_explicit_zero_calls_accept_with_zero() -> None:
    """happy: explicit 0 is accepted as factual zero (full snapshot / Пусто)."""
    client, accept = _client(codes=("d-1", "d-2"))
    token = _token(codes=("d-1", "d-2"))
    response = client.post(
        _PATH,
        data={"token": token, "qty_d-1": "0", "qty_d-2": "2"},
    )
    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {
        "d-1": Decimal("0"),
        "d-2": Decimal("2"),
    }
    assert accept.last_kwargs["partial"] is False


def test_post_oversized_body_returns_413_without_accept() -> None:
    """error: body over max_body_bytes → 413; Accept not called."""
    client, accept = _client(max_body_bytes=32, codes=("d-1",))
    response = client.post(
        _PATH,
        data="x" * 64,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    assert accept.calls == 0


def test_post_empty_or_missing_qty_returns_422_without_accept() -> None:
    """error: unanswered / missing qty key → 422; Accept not called."""
    client, accept = _client(codes=("d-1", "d-2"))
    token = _token(codes=("d-1", "d-2"))
    cases = (
        {"token": token, "qty_d-1": "3", "qty_d-2": ""},
        {"token": token, "qty_d-1": "3"},
    )
    for data in cases:
        response = client.post(_PATH, data=data)
        assert response.status_code == 422, data
        assert accept.calls == 0


def test_get_renders_empty_toggle_and_script() -> None:
    """happy: GET HTML has «Пусто» control and field_form.js hooks."""
    client, _accept = _client()
    response = client.get(_PATH, params={"token": _token()})
    assert response.status_code == 200
    body = response.text
    assert "Пусто" in body
    assert "data-empty-toggle" in body
    assert "field_form.js" in body
    assert "data-submit" in body


def test_post_strips_letters_in_qty() -> None:
    """edge: letters in qty are stripped (15с → 15)."""
    client, accept = _client(codes=("d-1",))
    token = _token(codes=("d-1",))
    response = client.post(_PATH, data={"token": token, "qty_d-1": "15с"})
    assert response.status_code == 200
    assert accept.calls == 1
    assert accept.last_kwargs["quantities"] == {"d-1": Decimal("15")}


def test_get_bad_token_returns_4xx_without_accept() -> None:
    """error: bad token → 4xx HTML; Accept not called."""
    client, accept = _client()
    response = client.get(_PATH, params={"token": "not-a-token"})
    assert response.status_code in {400, 401, 403, 422}
    assert accept.calls == 0
    assert "token" in response.text.lower() or "ссылк" in response.text.lower()


def test_post_bad_or_wrong_purpose_token_returns_4xx_without_accept() -> None:
    """error: POST bad / wrong-purpose / expired token → 4xx; Accept not called."""
    client, accept = _client(codes=("d-1",), token_max_age_hours=24.0)
    cases = (
        "not-a-token",
        _token(codes=("d-1",), purpose="micromarket_inventory_as_of"),
        create_micromarket_inventory_form_token(
            MicromarketInventoryFormTokenPayload(
                purpose="micromarket_inventory_now",
                technician_id=_TECH,
                machine_code=_MACHINE,
                fingerprint_id="fp-expired",
                product_codes=("d-1",),
                issued_at=datetime(2020, 1, 1, tzinfo=UTC),
                nonce="n-expired",
            ),
            _SECRET,
        ),
    )
    for token in cases:
        response = client.post(_PATH, data={"token": token, "qty_d-1": "1"})
        assert response.status_code in {400, 401, 403, 422}, token
        assert accept.calls == 0


def test_post_qty_above_max_returns_422_without_accept() -> None:
    """error: qty above max → 422 + form error; Accept not called."""
    client, accept = _client(qty_max=30, codes=("d-1",))
    token = _token(codes=("d-1",))
    response = client.post(_PATH, data={"token": token, "qty_d-1": "31"})
    assert response.status_code == 422
    assert accept.calls == 0
    assert "30" in response.text


def test_post_accept_visit_finalized_reject_returns_409() -> None:
    """error: Accept VisitFinalized reject → 409 with Russian freeze message."""
    accept = _RecordingAccept(error=VisitFinalizedRecountRejected("visit finalized"))
    client, _ = _client(accept=accept, codes=("d-1",))
    token = _token(codes=("d-1",))
    response = client.post(_PATH, data={"token": token, "qty_d-1": "1"})
    assert response.status_code == 409
    assert "визит завершён" in response.text.lower()
    assert "visit finalized" not in response.text.lower()


def test_field_form_css_viewport_contract() -> None:
    """mobile CSS contract: viewport-oriented large controls; no admin chrome."""
    css = _CSS.read_text(encoding="utf-8")
    assert "max-width" in css.lower() or "100vw" in css.lower()
    assert "font-size" in css.lower() or "min-height" in css.lower()
    assert "admin-sidebar" not in css
