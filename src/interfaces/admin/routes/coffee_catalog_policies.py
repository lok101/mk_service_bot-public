from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_POLICY_PROFILE_IDS,
    FormInventoryPolicyProfileId,
    FormInventoryPolicyStore,
    ensure_coffee_policy_profiles,
    upsert_policy_line,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    origin_allowed,
    page_context,
    read_admin_body,
    require_panel,
)
from src.interfaces.admin.routes.coffee_catalog_support import (
    COFFEE_INGREDIENTS_HREF,
    ingredient_names_by_number,
    parse_pack_size_field,
    policy_profile_id,
    policy_qty_unit_label,
    policy_show_radio,
)

__all__ = ["register_coffee_catalog_policy_routes"]


@beartype
def register_coffee_catalog_policy_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    store: DomainProductStore,
    policy_store: FormInventoryPolicyStore | None,
) -> None:
    def _policies_page(
        request: Request,
        *,
        profile_id: FormInventoryPolicyProfileId,
        error: str | None = None,
    ) -> Response:
        assert policy_store is not None
        ensure_coffee_policy_profiles(policy_store)
        profile = policy_store.get_profile(profile_id)
        lines = policy_store.list_lines(profile_id)
        input_mode = profile.input_mode.value if profile is not None else ""
        show_radio = policy_show_radio(profile_id)
        names_by_number = ingredient_names_by_number(store)
        return _TEMPLATES.TemplateResponse(
            request,
            "coffee_form_policies.html",
            page_context(
                request,
                deps,
                title="Политики qty кофейных форм",
                profile_id=profile_id,
                profile_ids=COFFEE_POLICY_PROFILE_IDS,
                qty_unit_label=policy_qty_unit_label(input_mode),
                show_radio=show_radio,
                show_min_max=not show_radio,
                lines=tuple(
                    {
                        "domain_number": line.domain_number,
                        "name": names_by_number.get(line.domain_number, "—"),
                        "min_qty": str(line.min_qty),
                        "max_qty": str(line.max_qty),
                        "radio_n": "" if line.radio_n is None else str(line.radio_n),
                        "form_label": line.form_label,
                        "form_hint": line.form_hint,
                    }
                    for line in lines
                ),
                can_edit=True,
                error=error,
            ),
        )

    @router.get(
        "/coffee-form-policies",
        response_class=HTMLResponse,
        name="admin_coffee_form_policies",
    )
    async def coffee_form_policies(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if policy_store is None:
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        profile_id = policy_profile_id(
            str(request.query_params.get("profile") or COFFEE_LOADING_PROFILE_ID),
        )
        return _policies_page(request, profile_id=profile_id)

    @router.post(
        "/coffee-form-policies",
        name="admin_coffee_form_policies_bulk_save",
    )
    async def coffee_form_policies_bulk_save(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request) or policy_store is None:
            return RedirectResponse("/admin/coffee-form-policies", status_code=303)
        body = (await read_admin_body(request, deps)).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        profile_id = policy_profile_id(
            (parsed.get("profile_id") or [COFFEE_LOADING_PROFILE_ID])[-1].strip()
        )
        action = (parsed.get("action") or [""])[-1].strip()
        if action != "bulk_save":
            return _policies_page(
                request,
                profile_id=profile_id,
                error="Неизвестное действие",
            )

        domain_numbers = list(parsed.get("domain_number") or [])
        form_labels = list(parsed.get("form_label") or [])
        form_hints = list(parsed.get("form_hint") or [])
        show_radio = policy_show_radio(profile_id)
        if len(domain_numbers) != len(form_labels) or len(domain_numbers) != len(form_hints):
            return _policies_page(
                request,
                profile_id=profile_id,
                error="Несогласованные поля формы",
            )
        if show_radio:
            radios = list(parsed.get("radio_n") or [])
            if len(domain_numbers) != len(radios):
                return _policies_page(
                    request,
                    profile_id=profile_id,
                    error="Несогласованные поля формы",
                )
            prepared: list[tuple[str, Decimal, Decimal, int | None, str, str]] = []
            for domain_number, radio_raw, form_label, form_hint in zip(
                domain_numbers,
                radios,
                form_labels,
                form_hints,
                strict=True,
            ):
                number = domain_number.strip()
                radio_trimmed = radio_raw.strip()
                radio_n = int(radio_trimmed) if radio_trimmed.isdigit() else None
                if not number or radio_n is None:
                    return _policies_page(
                        request,
                        profile_id=profile_id,
                        error="Укажите Radio N для каждой строки",
                    )
                existing = policy_store.get_line(profile_id, number)
                prepared.append(
                    (
                        number,
                        existing.min_qty if existing is not None else Decimal("0"),
                        existing.max_qty if existing is not None else Decimal(radio_n),
                        radio_n,
                        form_label,
                        form_hint,
                    )
                )
        else:
            mins = list(parsed.get("min_qty") or [])
            maxs = list(parsed.get("max_qty") or [])
            if not (len(domain_numbers) == len(mins) == len(maxs)):
                return _policies_page(
                    request,
                    profile_id=profile_id,
                    error="Несогласованные поля формы",
                )
            prepared = []
            for domain_number, min_raw, max_raw, form_label, form_hint in zip(
                domain_numbers,
                mins,
                maxs,
                form_labels,
                form_hints,
                strict=True,
            ):
                number = domain_number.strip()
                min_qty = parse_pack_size_field(min_raw)
                max_qty = parse_pack_size_field(max_raw)
                if not number or min_qty is None or max_qty is None:
                    return _policies_page(
                        request,
                        profile_id=profile_id,
                        error="Укажите Min и Max для каждой строки",
                    )
                prepared.append((number, min_qty, max_qty, None, form_label, form_hint))

        for sort_order, (number, min_qty, max_qty, radio_n, form_label, form_hint) in enumerate(
            prepared
        ):
            upsert_policy_line(
                policy_store,
                profile_id=profile_id,
                domain_number=number,
                min_qty=min_qty,
                max_qty=max_qty,
                radio_n=radio_n,
                sort_order=sort_order,
                form_label=form_label,
                form_hint=form_hint,
            )
        return RedirectResponse(
            f"/admin/coffee-form-policies?profile={profile_id}",
            status_code=303,
        )
