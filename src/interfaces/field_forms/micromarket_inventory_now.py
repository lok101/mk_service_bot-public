from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import parse_qs
from uuid import uuid4
from zoneinfo import ZoneInfo

from beartype import beartype
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.application.micromarket_loading.accept_inventory import VisitFinalizedRecountRejected
from src.application.micromarket_loading.inventory_form_pages import (
    InventoryFormPage,
    flatten_inventory_form_page_codes,
)
from src.application.micromarket_loading.maintenance_gate import (
    last_micromarket_inventory_quantities_for_operational_day,
)
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    VisitFinalizedForDayPort,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.form_tokens import (
    MicromarketInventoryFormTokenPayload,
    verify_micromarket_inventory_form_token,
)
from src.interfaces.field_forms.http_common import form_template_response
from src.interfaces.field_forms.qty_field_rule import (
    QtyFieldRule,
    make_qty_field_rule,
    parse_qty_against_rule,
)
from src.interfaces.http.bounded_body import read_bounded_request_body

_PACKAGE_DIR = Path(__file__).parent
_STATIC_DIR = _PACKAGE_DIR / "static"
_FORM_PATH = "/forms/micromarket-inventory/now"
_PURPOSE: Literal["micromarket_inventory_now"] = "micromarket_inventory_now"
_FREEZE_MESSAGE = "Визит завершён. Пересчёт за текущие операционные сутки нельзя изменить."


@runtime_checkable
class AcceptMicromarketInventoryFieldForm(Protocol):
    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: Literal["now", "as_of"],
        submitted_at: datetime,
        quantities: Mapping[str, Decimal],
        inventory_id: str,
        as_of_from_form: datetime | None,
        partial: bool = True,
    ) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class FieldFormLineView:
    code: str
    name: str
    value: str = ""
    qty_rule: QtyFieldRule | None = None


@beartype
@dataclass(frozen=True, slots=True)
class FieldFormSectionView:
    title: str
    lines: tuple[FieldFormLineView, ...]


@beartype
@dataclass(slots=True)
class MicromarketInventoryNowFieldFormDeps:
    now_token_secret: str
    qty_max: int
    accept_micromarket_inventory: AcceptMicromarketInventoryFieldForm
    load_pages: Callable[[str], Sequence[InventoryFormPage]]
    products: DomainProductStore | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)
    token_max_age_hours: float | None = None
    visit_finalized: VisitFinalizedForDayPort | None = None
    stock_store: MicromarketDeviceStockStore | None = None
    timezone: ZoneInfo | None = None
    day_end_hour: int | None = None
    max_body_bytes: int = 1_048_576


@beartype
def register_micromarket_inventory_now_field_form_routes(
    app: FastAPI,
    deps: MicromarketInventoryNowFieldFormDeps,
) -> None:
    if not any(getattr(route, "path", None) == "/forms/static" for route in app.routes):
        app.mount(
            "/forms/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="field_form_static",
        )

    @app.get(_FORM_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def get_micromarket_inventory_now(
        request: Request,
        token: str = "",
    ) -> HTMLResponse:
        return await _render_get(request, deps=deps, token=token)

    @app.post(_FORM_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def post_micromarket_inventory_now(request: Request) -> HTMLResponse:
        body = (
            await read_bounded_request_body(request, max_body_bytes=deps.max_body_bytes)
        ).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        token = parsed.get("token", [""])[-1]
        raw_values = {
            key.removeprefix("qty_"): values[-1]
            for key, values in parsed.items()
            if key.startswith("qty_")
        }
        return await _render_post(
            request,
            deps=deps,
            token=token,
            raw_values=raw_values,
        )


@beartype
def _is_finalized(deps: MicromarketInventoryNowFieldFormDeps, *, machine_code: str) -> bool:
    if deps.visit_finalized is None:
        return False
    return deps.visit_finalized.is_finalized(machine_code, deps.clock())


@beartype
def _prefill_values(
    deps: MicromarketInventoryNowFieldFormDeps,
    *,
    machine_code: str,
    product_codes: Sequence[str],
) -> dict[str, str]:
    if deps.stock_store is None or deps.timezone is None or deps.day_end_hour is None:
        return {}
    events = deps.stock_store.list_events(machine_code)
    quantities = last_micromarket_inventory_quantities_for_operational_day(
        events,
        checked_at=deps.clock(),
        timezone=deps.timezone,
        day_end_hour=deps.day_end_hour,
    )
    allowed = set(product_codes)
    return {
        code: format(qty.normalize(), "f").rstrip("0").rstrip(".") or "0"
        for code, qty in quantities.items()
        if code in allowed
    }


@beartype
async def _render_get(
    request: Request,
    *,
    deps: MicromarketInventoryNowFieldFormDeps,
    token: str,
) -> HTMLResponse:
    try:
        payload = _verify_token(deps, token=token)
    except ValueError as error:
        return form_template_response(
            request,
            "micromarket_inventory_now.html",
            {
                "token": "",
                "sections": (),
                "error": str(error) or "Недействительная ссылка",
                "success": False,
                "read_only": False,
                "freeze_message": None,
            },
            status_code=422,
        )
    values = _prefill_values(
        deps,
        machine_code=payload.machine_code,
        product_codes=payload.product_codes,
    )
    read_only = _is_finalized(deps, machine_code=payload.machine_code)
    sections = await _sections_for_payload(deps, payload=payload, values=values)
    return form_template_response(
        request,
        "micromarket_inventory_now.html",
        {
            "token": token,
            "sections": sections,
            "error": None,
            "success": False,
            "read_only": read_only,
            "freeze_message": _FREEZE_MESSAGE if read_only else None,
        },
    )


@beartype
async def _render_post(
    request: Request,
    *,
    deps: MicromarketInventoryNowFieldFormDeps,
    token: str,
    raw_values: Mapping[str, str],
) -> HTMLResponse:
    try:
        payload = _verify_token(deps, token=token)
    except ValueError as error:
        return form_template_response(
            request,
            "micromarket_inventory_now.html",
            {
                "token": "",
                "sections": (),
                "error": str(error) or "Недействительная ссылка",
                "success": False,
                "read_only": False,
                "freeze_message": None,
            },
            status_code=422,
        )

    if _is_finalized(deps, machine_code=payload.machine_code):
        sections = await _sections_for_payload(deps, payload=payload, values=dict(raw_values))
        return form_template_response(
            request,
            "micromarket_inventory_now.html",
            {
                "token": token,
                "sections": sections,
                "error": _FREEZE_MESSAGE,
                "success": False,
                "read_only": True,
                "freeze_message": _FREEZE_MESSAGE,
            },
            status_code=409,
        )

    try:
        quantities = _parse_quantities(
            product_codes=payload.product_codes,
            raw_values=raw_values,
            qty_max=deps.qty_max,
            products=deps.products,
        )
    except ValueError as error:
        sections = await _sections_for_payload(deps, payload=payload, values=dict(raw_values))
        return form_template_response(
            request,
            "micromarket_inventory_now.html",
            {
                "token": token,
                "sections": sections,
                "error": str(error),
                "success": False,
                "read_only": False,
                "freeze_message": None,
            },
            status_code=422,
        )

    inventory_id = f"field-form-now:{uuid4()}"
    try:
        await asyncio.to_thread(
            deps.accept_micromarket_inventory.execute,
            machine_code=payload.machine_code,
            mode="now",
            submitted_at=deps.clock(),
            quantities=quantities,
            inventory_id=inventory_id,
            as_of_from_form=None,
            partial=False,
        )
    except VisitFinalizedRecountRejected:
        sections = await _sections_for_payload(deps, payload=payload, values=dict(raw_values))
        return form_template_response(
            request,
            "micromarket_inventory_now.html",
            {
                "token": token,
                "sections": sections,
                "error": _FREEZE_MESSAGE,
                "success": False,
                "read_only": True,
                "freeze_message": _FREEZE_MESSAGE,
            },
            status_code=409,
        )
    except ValueError as error:
        sections = await _sections_for_payload(deps, payload=payload, values=dict(raw_values))
        return form_template_response(
            request,
            "micromarket_inventory_now.html",
            {
                "token": token,
                "sections": sections,
                "error": str(error),
                "success": False,
                "read_only": False,
                "freeze_message": None,
            },
            status_code=422,
        )

    return form_template_response(
        request,
        "micromarket_inventory_now.html",
        {
            "token": token,
            "sections": (),
            "error": None,
            "success": True,
            "read_only": False,
            "freeze_message": None,
        },
    )


@beartype
def _verify_token(
    deps: MicromarketInventoryNowFieldFormDeps,
    *,
    token: str,
) -> MicromarketInventoryFormTokenPayload:
    if not token.strip():
        raise ValueError("Нужна ссылка с токеном формы")
    return verify_micromarket_inventory_form_token(
        token,
        deps.now_token_secret,
        expected_purpose=_PURPOSE,
        max_age_hours=deps.token_max_age_hours,
    )


@beartype
def _micromarket_qty_rule(qty_max: int) -> QtyFieldRule:
    return make_qty_field_rule(
        min_qty=Decimal("0"),
        max_qty=Decimal(qty_max),
        integer=False,
    )


@beartype
def _parse_quantities(
    *,
    product_codes: Sequence[str],
    raw_values: Mapping[str, str],
    qty_max: int,
    products: DomainProductStore | None = None,
) -> dict[str, Decimal]:
    rule = _micromarket_qty_rule(qty_max)
    quantities: dict[str, Decimal] = {}
    for code in product_codes:
        label = _product_name(code, products)
        if code not in raw_values:
            raise ValueError(f"Нужен ответ для {label}")
        quantities[code] = parse_qty_against_rule(raw_values[code], rule, label=label)
    return quantities


@beartype
async def _sections_for_payload(
    deps: MicromarketInventoryNowFieldFormDeps,
    *,
    payload: MicromarketInventoryFormTokenPayload,
    values: Mapping[str, str],
) -> tuple[FieldFormSectionView, ...]:
    pages = tuple(await asyncio.to_thread(deps.load_pages, payload.machine_code))
    page_codes = flatten_inventory_form_page_codes(pages)
    if page_codes == payload.product_codes and pages:
        return tuple(
            FieldFormSectionView(
                title=page.title,
                lines=tuple(
                    FieldFormLineView(
                        code=code,
                        name=_product_name(code, deps.products),
                        value=values.get(code, ""),
                        qty_rule=_micromarket_qty_rule(deps.qty_max),
                    )
                    for code in page.product_codes
                ),
            )
            for page in pages
        )
    return (
        FieldFormSectionView(
            title="Позиции",
            lines=tuple(
                FieldFormLineView(
                    code=code,
                    name=_product_name(code, deps.products),
                    value=values.get(code, ""),
                    qty_rule=_micromarket_qty_rule(deps.qty_max),
                )
                for code in payload.product_codes
            ),
        ),
    )


@beartype
def _product_name(code: str, products: DomainProductStore | None) -> str:
    if products is None:
        return code
    product = products.get_by_number(code)
    if product is None:
        product = products.get_by_catalog_code(code)
    if product is None:
        return code
    name = product.name.strip()
    return name or code
