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
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_REVISION_PROFILE_ID,
    FormInventoryPolicyProfileId,
    FormInventoryPolicyStore,
)
from src.application.form_submissions import (
    FormSubmissionRejectedError,
    FormSubmissionValidationError,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    CoffeeFormPurpose,
    CoffeeFormTokenPayload,
    verify_coffee_form_token,
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
_REVISION_PATH = "/forms/coffee-revision"
_LOADING_PATH = "/forms/coffee-loading"
_REVISION_TITLE = "Ревизия"
_LOADING_TITLE = "Загрузка"
_MISSING_RADIO_N_MESSAGE = "нет radio_n у видимых ингредиентов кофе"


@runtime_checkable
class AcceptCoffeeFieldForm(Protocol):
    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        token: str,
        token_payload: CoffeeFormTokenPayload,
        answers: tuple[FormAnswer, ...],
        purpose: str = ...,
    ) -> object: ...


_SCALE_PER_ROW = 10


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeFieldFormLineView:
    code: str
    name: str
    value: str = ""
    hint: str = ""
    radio_n: int | None = None
    qty_rule: QtyFieldRule | None = None

    @property
    def scale_rows(self) -> tuple[tuple[int, ...], ...]:
        """Positive radio marks 1…radio_n chunked for quiet-scale rows."""
        if self.radio_n is None or self.radio_n < 1:
            return ()
        marks = tuple(range(1, self.radio_n + 1))
        return tuple(marks[i : i + _SCALE_PER_ROW] for i in range(0, len(marks), _SCALE_PER_ROW))


@beartype
@dataclass(slots=True)
class CoffeeFieldFormDeps:
    revision_token_secret: str
    loading_token_secret: str
    qty_max: int
    accept_revision: AcceptCoffeeFieldForm
    accept_loading: AcceptCoffeeFieldForm
    products: DomainProductStore
    policies: FormInventoryPolicyStore
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)
    token_max_age_hours: float | None = None
    max_body_bytes: int = 1_048_576
    form_id_revision: str = "coffee-revision-field-form"
    form_id_loading: str = "coffee-loading-field-form"


@beartype
def register_coffee_field_form_routes(app: FastAPI, deps: CoffeeFieldFormDeps) -> None:
    if not any(getattr(route, "path", None) == "/forms/static" for route in app.routes):
        app.mount(
            "/forms/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="field_form_static",
        )

    @app.get(_REVISION_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def get_coffee_revision(request: Request, token: str = "") -> HTMLResponse:
        return await _render_get(
            request,
            deps=deps,
            token=token,
            purpose="revision",
        )

    @app.post(_REVISION_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def post_coffee_revision(request: Request) -> HTMLResponse:
        return await _handle_post(request, deps=deps, purpose="revision")

    @app.get(_LOADING_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def get_coffee_loading(request: Request, token: str = "") -> HTMLResponse:
        return await _render_get(
            request,
            deps=deps,
            token=token,
            purpose="loading",
        )

    @app.post(_LOADING_PATH, response_class=HTMLResponse, include_in_schema=False)
    async def post_coffee_loading(request: Request) -> HTMLResponse:
        return await _handle_post(request, deps=deps, purpose="loading")


@beartype
async def _handle_post(
    request: Request,
    *,
    deps: CoffeeFieldFormDeps,
    purpose: CoffeeFormPurpose,
) -> HTMLResponse:
    body = (await read_bounded_request_body(request, max_body_bytes=deps.max_body_bytes)).decode(
        "utf-8"
    )
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
        purpose=purpose,
        raw_values=raw_values,
    )


@beartype
async def _render_get(
    request: Request,
    *,
    deps: CoffeeFieldFormDeps,
    token: str,
    purpose: CoffeeFormPurpose,
) -> HTMLResponse:
    try:
        payload = _verify_token(deps, token=token, purpose=purpose)
    except ValueError as error:
        return _error_response(
            request,
            purpose=purpose,
            token="",
            error=str(error) or "Недействительная ссылка",
            status_code=422,
        )
    try:
        lines = _lines_for_payload(deps, payload=payload, values={}, purpose=purpose)
    except ValueError as error:
        return _error_response(
            request,
            purpose=purpose,
            token=token,
            error=str(error) or _MISSING_RADIO_N_MESSAGE,
            status_code=422,
        )
    return form_template_response(
        request,
        "coffee_form.html",
        _template_context(
            token=token,
            lines=lines,
            error=None,
            success=False,
            purpose=purpose,
        ),
    )


@beartype
async def _render_post(
    request: Request,
    *,
    deps: CoffeeFieldFormDeps,
    token: str,
    purpose: CoffeeFormPurpose,
    raw_values: Mapping[str, str],
) -> HTMLResponse:
    try:
        payload = _verify_token(deps, token=token, purpose=purpose)
    except ValueError as error:
        return _error_response(
            request,
            purpose=purpose,
            token="",
            error=str(error) or "Недействительная ссылка",
            status_code=422,
        )

    try:
        visible_codes = _ordered_visible_codes(deps, payload=payload, purpose=purpose)
    except ValueError as error:
        return _error_response(
            request,
            purpose=purpose,
            token=token,
            error=str(error) or _MISSING_RADIO_N_MESSAGE,
            status_code=422,
        )
    try:
        _reject_unknown_codes(raw_values=raw_values, allowed=visible_codes)
        quantities = _parse_quantities(
            deps=deps,
            purpose=purpose,
            product_codes=visible_codes,
            raw_values=raw_values,
        )
    except ValueError as error:
        try:
            lines = _lines_for_payload(
                deps,
                payload=payload,
                values=dict(raw_values),
                purpose=purpose,
            )
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
                purpose=purpose,
            ),
            status_code=422,
        )

    answers = tuple(
        FormAnswer(title=code, value=format(qty.normalize(), "f"))
        for code, qty in quantities.items()
    )
    try:
        await asyncio.to_thread(
            _accept_for_purpose(deps, purpose).execute,
            form_id=_form_id(deps, purpose),
            submitted_at=deps.clock(),
            token=token,
            token_payload=payload,
            answers=answers,
            purpose=purpose,
        )
    except FormSubmissionRejectedError as error:
        try:
            lines = _lines_for_payload(
                deps,
                payload=payload,
                values=dict(raw_values),
                purpose=purpose,
            )
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
                purpose=purpose,
            ),
            status_code=409,
        )
    except (FormSubmissionValidationError, ValueError) as error:
        message = error.reason if isinstance(error, FormSubmissionValidationError) else str(error)
        try:
            lines = _lines_for_payload(
                deps,
                payload=payload,
                values=dict(raw_values),
                purpose=purpose,
            )
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
                purpose=purpose,
            ),
            status_code=422,
        )

    return form_template_response(
        request,
        "coffee_form.html",
        _template_context(
            token=token,
            lines=(),
            error=None,
            success=True,
            purpose=purpose,
        ),
    )


@beartype
def _verify_token(
    deps: CoffeeFieldFormDeps,
    *,
    token: str,
    purpose: CoffeeFormPurpose,
) -> CoffeeFormTokenPayload:
    if not token.strip():
        raise ValueError("Нужна ссылка с токеном формы")
    secret = deps.revision_token_secret if purpose == "revision" else deps.loading_token_secret
    return verify_coffee_form_token(
        token,
        secret,
        expected_purpose=purpose,
        max_age_hours=deps.token_max_age_hours,
    )


@beartype
def _visible_codes_from_payload(
    deps: CoffeeFieldFormDeps,
    *,
    payload: CoffeeFormTokenPayload,
) -> tuple[str, ...]:
    visible: list[str] = []
    for code in payload.product_codes:
        product = deps.products.get_by_number(code)
        if product is None:
            continue
        if product.kind != "coffee_ingredient" or product.hidden:
            continue
        visible.append(code)
    return tuple(visible)


@beartype
def _profile_id_for_purpose(purpose: CoffeeFormPurpose) -> FormInventoryPolicyProfileId:
    return COFFEE_LOADING_PROFILE_ID if purpose == "loading" else COFFEE_REVISION_PROFILE_ID


@beartype
def _ordered_visible_codes(
    deps: CoffeeFieldFormDeps,
    *,
    payload: CoffeeFormTokenPayload,
    purpose: CoffeeFormPurpose,
) -> tuple[str, ...]:
    visible = _visible_codes_from_payload(deps, payload=payload)
    visible_set = set(visible)
    profile_id = _profile_id_for_purpose(purpose)
    ordered = [
        line.domain_number
        for line in deps.policies.list_lines(profile_id)
        if line.domain_number in visible_set
    ]
    missing = visible_set.difference(ordered)
    if missing:
        sample = sorted(missing)[0]
        label = _catalog_name(deps, code=sample)
        if purpose == "loading":
            raise ValueError(_MISSING_RADIO_N_MESSAGE)
        raise ValueError(f"Нет политики ревизии для {label}")
    return tuple(ordered)


@beartype
def _catalog_name(deps: CoffeeFieldFormDeps, *, code: str) -> str:
    product = deps.products.get_by_number(code)
    if product is not None and product.name.strip():
        return product.name.strip()
    return code


@beartype
def _display_name(
    deps: CoffeeFieldFormDeps,
    *,
    code: str,
    form_label: str,
) -> str:
    trimmed = form_label.strip()
    if trimmed:
        return trimmed
    return _catalog_name(deps, code=code)


@beartype
def _lines_for_payload(
    deps: CoffeeFieldFormDeps,
    *,
    payload: CoffeeFormTokenPayload,
    values: Mapping[str, str],
    purpose: CoffeeFormPurpose,
) -> tuple[CoffeeFieldFormLineView, ...]:
    profile_id = _profile_id_for_purpose(purpose)
    lines: list[CoffeeFieldFormLineView] = []
    for code in _ordered_visible_codes(deps, payload=payload, purpose=purpose):
        policy_line = deps.policies.get_line(profile_id, code)
        if policy_line is None:
            label = _catalog_name(deps, code=code)
            if purpose == "loading":
                raise ValueError(_MISSING_RADIO_N_MESSAGE)
            raise ValueError(f"Нет политики ревизии для {label}")
        name = _display_name(deps, code=code, form_label=policy_line.form_label)
        hint = policy_line.form_hint.strip()
        radio_n: int | None = None
        qty_rule: QtyFieldRule | None = None
        if purpose == "loading":
            if policy_line.radio_n is None:
                raise ValueError(_MISSING_RADIO_N_MESSAGE)
            radio_n = policy_line.radio_n
        else:
            qty_rule = make_qty_field_rule(
                min_qty=policy_line.min_qty,
                max_qty=policy_line.max_qty,
                integer=False,
            )
        lines.append(
            CoffeeFieldFormLineView(
                code=code,
                name=name,
                value=values.get(code, ""),
                hint=hint,
                radio_n=radio_n,
                qty_rule=qty_rule,
            ),
        )
    return tuple(lines)


@beartype
def _template_context(
    *,
    token: str,
    lines: Sequence[CoffeeFieldFormLineView],
    error: str | None,
    success: bool,
    purpose: CoffeeFormPurpose,
) -> dict[str, object]:
    return {
        "token": token,
        "lines": lines,
        "error": error,
        "success": success,
        "form_title": _title(purpose),
        "form_path": _path(purpose),
        "input_ui": "radio" if purpose == "loading" else "text",
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
def _label_for_code(
    deps: CoffeeFieldFormDeps,
    *,
    purpose: CoffeeFormPurpose,
    code: str,
) -> str:
    profile_id = _profile_id_for_purpose(purpose)
    policy_line = deps.policies.get_line(profile_id, code)
    form_label = policy_line.form_label if policy_line is not None else ""
    return _display_name(deps, code=code, form_label=form_label)


@beartype
def _parse_quantities(
    *,
    deps: CoffeeFieldFormDeps,
    purpose: CoffeeFormPurpose,
    product_codes: Sequence[str],
    raw_values: Mapping[str, str],
) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    for code in product_codes:
        label = _label_for_code(deps, purpose=purpose, code=code)
        if code not in raw_values:
            raise ValueError(f"Нужен ответ для {label}")
        min_qty, max_qty = _bounds_for_code(deps, purpose=purpose, code=code, label=label)
        rule = make_qty_field_rule(
            min_qty=min_qty,
            max_qty=max_qty,
            integer=False,
        )
        quantities[code] = parse_qty_against_rule(raw_values[code], rule, label=label)
    return quantities


@beartype
def _bounds_for_code(
    deps: CoffeeFieldFormDeps,
    *,
    purpose: CoffeeFormPurpose,
    code: str,
    label: str,
) -> tuple[Decimal, Decimal]:
    if purpose == "revision":
        line = deps.policies.get_line(COFFEE_REVISION_PROFILE_ID, code)
        if line is None:
            raise ValueError(f"Нет политики ревизии для {label}")
        return line.min_qty, line.max_qty
    # loading: radio UI already caps 0…radio_n; keep env ceiling as hard stop
    return Decimal("0"), Decimal(deps.qty_max)


@beartype
def _accept_for_purpose(
    deps: CoffeeFieldFormDeps,
    purpose: CoffeeFormPurpose,
) -> AcceptCoffeeFieldForm:
    return deps.accept_revision if purpose == "revision" else deps.accept_loading


@beartype
def _form_id(deps: CoffeeFieldFormDeps, purpose: CoffeeFormPurpose) -> str:
    return deps.form_id_revision if purpose == "revision" else deps.form_id_loading


@beartype
def _title(purpose: CoffeeFormPurpose) -> str:
    return _REVISION_TITLE if purpose == "revision" else _LOADING_TITLE


@beartype
def _path(purpose: CoffeeFormPurpose) -> str:
    return _REVISION_PATH if purpose == "revision" else _LOADING_PATH


@beartype
def _error_response(
    request: Request,
    *,
    purpose: CoffeeFormPurpose,
    token: str,
    error: str,
    status_code: int,
) -> HTMLResponse:
    return form_template_response(
        request,
        "coffee_form.html",
        _template_context(
            token=token,
            lines=(),
            error=error,
            success=False,
            purpose=purpose,
        ),
        status_code=status_code,
    )
