from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qs

from beartype import beartype
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.application.form_inventory_policy import (
    TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
    FormInventoryPolicyStore,
)
from src.application.form_submissions import (
    FormSubmissionRejectedError,
    FormSubmissionValidationError,
)
from src.application.product_identity import packaging_is_form_ready
from src.application.product_identity.ports import DomainProductStore
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    TechnicianWarehouseInventoryTokenPayload,
    verify_technician_warehouse_inventory_token,
)
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.interfaces.field_forms.http_common import form_template_response
from src.interfaces.field_forms.qty_field_rule import (
    QtyFieldRule,
    make_qty_field_rule,
    parse_qty_against_rule,
)
from src.interfaces.http.bounded_body import read_bounded_request_body

_PACKAGE_DIR = Path(__file__).parent
_STATIC_DIR = _PACKAGE_DIR / "static"
_FORM_PATH = "/forms/technician-warehouse-inventory"
_FORM_TITLE = "Инвентаризация склада"
_MISSING_PACK_OR_POLICY_MESSAGE = "нет упаковки или политики qty у видимых ингредиентов кофе"
_EMPTY_INGREDIENTS_MESSAGE = "нет видимых ингредиентов кофе"


@runtime_checkable
class AcceptWarehouseFieldForm(Protocol):
    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> object: ...


@runtime_checkable
class WarehouseFieldFormErrorNotifier(Protocol):
    @beartype
    async def notify(self, *, technician_id: TechnicianId, reason: str) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class WarehouseFieldFormLineView:
    code: str
    name: str
    value: str = ""
    hint: str = ""
    qty_rule: QtyFieldRule | None = None


@beartype
@dataclass(slots=True)
class TechnicianWarehouseInventoryFieldFormDeps:
    token_secret: str
    qty_max: int
    accept: AcceptWarehouseFieldForm
    products: DomainProductStore
    policies: FormInventoryPolicyStore
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)
    token_max_age_hours: float | None = None
    max_body_bytes: int = 1_048_576
    form_id: str = "technician-warehouse-inventory-field-form"
    error_notifier: WarehouseFieldFormErrorNotifier | None = None


@beartype
def register_technician_warehouse_inventory_field_form_routes(
    app: FastAPI,
    deps: TechnicianWarehouseInventoryFieldFormDeps,
) -> None:
    if not any(getattr(route, "path", None) == "/forms/static" for route in app.routes):
        app.mount(
            "/forms/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="field_form_static",
        )

    @app.get(_FORM_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def get_warehouse_inventory(request: Request, token: str = "") -> HTMLResponse:
        return await _render_get(request, deps=deps, token=token)

    @app.post(_FORM_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def post_warehouse_inventory(request: Request) -> HTMLResponse:
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
        return await _render_post(request, deps=deps, token=token, raw_values=raw_values)


@beartype
async def _render_get(
    request: Request,
    *,
    deps: TechnicianWarehouseInventoryFieldFormDeps,
    token: str,
) -> HTMLResponse:
    try:
        _verify_token(deps, token=token)
        lines = _lines(deps, values={})
    except ValueError as error:
        return _error_response(
            request,
            token="" if "токен" in str(error).lower() or "ссылк" in str(error).lower() else token,
            error=str(error) or "Недействительная ссылка",
            status_code=422,
        )
    return form_template_response(
        request,
        "coffee_form.html",
        _template_context(token=token, lines=lines, error=None, success=False),
    )


@beartype
async def _render_post(
    request: Request,
    *,
    deps: TechnicianWarehouseInventoryFieldFormDeps,
    token: str,
    raw_values: Mapping[str, str],
) -> HTMLResponse:
    payload: TechnicianWarehouseInventoryTokenPayload | None = None
    try:
        payload = _verify_token(deps, token=token)
        codes = _visible_codes(deps)
        _reject_unknown_codes(raw_values=raw_values, allowed=codes)
        quantities = _parse_quantities(
            deps=deps,
            product_codes=codes,
            raw_values=raw_values,
            qty_max=deps.qty_max,
        )
    except ValueError as error:
        try:
            lines = _lines(deps, values=dict(raw_values))
        except ValueError:
            lines = ()
        return form_template_response(
            request,
            "coffee_form.html",
            _template_context(
                token=token,
                lines=lines,
                error=str(error),
                success=False,
            ),
            status_code=422,
        )

    answers = tuple(
        FormAnswer(title=code, value=format(qty.normalize(), "f"))
        for code, qty in quantities.items()
    )
    try:
        await asyncio.to_thread(
            deps.accept.execute,
            form_id=deps.form_id,
            submitted_at=deps.clock(),
            form_token=token,
            token_payload=payload,
            answers=answers,
        )
    except FormSubmissionRejectedError as error:
        try:
            lines = _lines(deps, values=dict(raw_values))
        except ValueError:
            lines = ()
        return form_template_response(
            request,
            "coffee_form.html",
            _template_context(
                token=token,
                lines=lines,
                error=error.reason,
                success=False,
            ),
            status_code=409,
        )
    except TechnicianWarehouseConcurrencyError as error:
        try:
            lines = _lines(deps, values=dict(raw_values))
        except ValueError:
            lines = ()
        return form_template_response(
            request,
            "coffee_form.html",
            _template_context(
                token=token,
                lines=lines,
                error=str(error),
                success=False,
            ),
            status_code=409,
        )
    except (FormSubmissionValidationError, ValueError) as error:
        message = error.reason if isinstance(error, FormSubmissionValidationError) else str(error)
        try:
            lines = _lines(deps, values=dict(raw_values))
        except ValueError:
            lines = ()
        return form_template_response(
            request,
            "coffee_form.html",
            _template_context(
                token=token,
                lines=lines,
                error=message,
                success=False,
            ),
            status_code=422,
        )

    return form_template_response(
        request,
        "coffee_form.html",
        _template_context(token=token, lines=(), error=None, success=True),
    )


@beartype
def _verify_token(
    deps: TechnicianWarehouseInventoryFieldFormDeps,
    *,
    token: str,
) -> TechnicianWarehouseInventoryTokenPayload:
    if not token.strip():
        raise ValueError("Нужна ссылка с токеном формы")
    return verify_technician_warehouse_inventory_token(
        token,
        deps.token_secret,
        max_age_hours=deps.token_max_age_hours,
    )


@beartype
def _visible_codes(deps: TechnicianWarehouseInventoryFieldFormDeps) -> tuple[str, ...]:
    visible = {
        product.number
        for product in deps.products.list_visible()
        if product.kind == "coffee_ingredient"
    }
    if not visible:
        raise ValueError(_EMPTY_INGREDIENTS_MESSAGE)
    ordered: list[str] = []
    for line in deps.policies.list_lines(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID):
        if line.domain_number not in visible:
            continue
        product = deps.products.get_by_number(line.domain_number)
        if product is None or not packaging_is_form_ready(
            unit=product.unit,
            pack_size=product.pack_size,
        ):
            raise ValueError(_MISSING_PACK_OR_POLICY_MESSAGE)
        ordered.append(line.domain_number)
    if visible.difference(ordered):
        raise ValueError(_MISSING_PACK_OR_POLICY_MESSAGE)
    return tuple(ordered)


@beartype
def _lines(
    deps: TechnicianWarehouseInventoryFieldFormDeps,
    *,
    values: Mapping[str, str],
) -> tuple[WarehouseFieldFormLineView, ...]:
    lines: list[WarehouseFieldFormLineView] = []
    for code in _visible_codes(deps):
        policy_line = deps.policies.get_line(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID, code)
        product = deps.products.get_by_number(code)
        catalog = product.name.strip() if product is not None and product.name.strip() else code
        form_label = policy_line.form_label.strip() if policy_line is not None else ""
        name = form_label or catalog
        hint = policy_line.form_hint.strip() if policy_line is not None else ""
        lines.append(
            WarehouseFieldFormLineView(
                code=code,
                name=name,
                value=values.get(code, ""),
                hint=hint,
                qty_rule=_warehouse_qty_rule(deps.qty_max),
            ),
        )
    return tuple(lines)


@beartype
def _template_context(
    *,
    token: str,
    lines: Sequence[WarehouseFieldFormLineView],
    error: str | None,
    success: bool,
) -> dict[str, object]:
    return {
        "token": token,
        "lines": lines,
        "error": error,
        "success": success,
        "form_title": _FORM_TITLE,
        "form_path": _FORM_PATH,
        "input_ui": "text",
        "require_all_lines": True,
        "hide_empty_toggle": False,
    }


@beartype
def _reject_unknown_codes(
    *,
    raw_values: Mapping[str, str],
    allowed: tuple[str, ...],
) -> None:
    allowed_set = set(allowed)
    for code in raw_values:
        if code not in allowed_set:
            raise ValueError(f"Неизвестный ингредиент {code}")


@beartype
def _warehouse_qty_rule(qty_max: int) -> QtyFieldRule:
    return make_qty_field_rule(
        min_qty=Decimal("0"),
        max_qty=Decimal(qty_max),
        integer=True,
    )


@beartype
def _label_for_code(
    deps: TechnicianWarehouseInventoryFieldFormDeps,
    *,
    code: str,
) -> str:
    policy_line = deps.policies.get_line(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID, code)
    form_label = policy_line.form_label.strip() if policy_line is not None else ""
    if form_label:
        return form_label
    product = deps.products.get_by_number(code)
    if product is not None and product.name.strip():
        return product.name.strip()
    return code


@beartype
def _parse_quantities(
    *,
    deps: TechnicianWarehouseInventoryFieldFormDeps,
    product_codes: Sequence[str],
    raw_values: Mapping[str, str],
    qty_max: int,
) -> dict[str, Decimal]:
    rule = _warehouse_qty_rule(qty_max)
    quantities: dict[str, Decimal] = {}
    for code in product_codes:
        label = _label_for_code(deps, code=code)
        if code not in raw_values:
            raise ValueError(f"Нужен ответ для {label}")
        quantities[code] = parse_qty_against_rule(raw_values[code], rule, label=label)
    return quantities


@beartype
def _error_response(
    request: Request,
    *,
    token: str,
    error: str,
    status_code: int,
) -> HTMLResponse:
    return form_template_response(
        request,
        "coffee_form.html",
        _template_context(token=token, lines=(), error=error, success=False),
        status_code=status_code,
    )
