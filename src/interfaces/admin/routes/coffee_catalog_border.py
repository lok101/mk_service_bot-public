from __future__ import annotations

import json
from urllib.parse import quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.application.product_identity import (
    BorderQueueDecision,
    BorderRegistrationStore,
    DomainProductRejected,
    apply_border_queue,
    list_unregistered_queue,
)
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    origin_allowed,
    page_context,
    require_panel,
)
from src.interfaces.admin.planogram_product_options import planogram_product_options
from src.interfaces.admin.routes.coffee_catalog_support import ms_catalog_names

__all__ = ["register_coffee_catalog_border_routes"]


@beartype
def register_coffee_catalog_border_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    border: BorderRegistrationStore,
) -> None:
    @router.get(
        "/coffee-border-registration",
        response_class=HTMLResponse,
        name="admin_coffee_border_registration",
    )
    async def coffee_border_registration(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        ms_names = ms_catalog_names(deps)
        ignored = tuple(
            {"ms_code": item.ms_code, "ms_name": ms_names.get(item.ms_code)}
            for item in border.list_ignored()
        )
        queue = list_unregistered_queue(products=store, border=border)
        queue_rows = tuple({"ms_code": code, "ms_name": ms_names.get(code)} for code in queue)
        options = planogram_product_options(store, kind="coffee_ingredient")
        options_json = json.dumps(
            [
                {
                    "domain_product_id": opt.domain_product_id,
                    "name": opt.name,
                    "number": opt.number,
                    "linked": opt.linked,
                }
                for opt in options
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).replace("<", "\\u003c")
        flash = request.query_params.get("error")
        return _TEMPLATES.TemplateResponse(
            request,
            "coffee_border_registration.html",
            page_context(
                request,
                deps,
                title="Регистрация на границе МС→техник",
                queue_rows=queue_rows,
                ignored=ignored,
                ingredient_options_json=options_json,
                flash=flash,
            ),
        )

    @router.post(
        "/coffee-border-registration/save",
        name="admin_coffee_border_save",
    )
    async def coffee_border_save(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return RedirectResponse("/admin/coffee-border-registration", status_code=303)
        form = await request.form()
        codes = [str(v) for v in form.getlist("ms_code")]
        product_ids = [str(v) for v in form.getlist("domain_product_id")]
        ignored_flags = [str(v) for v in form.getlist("ignored")]
        decisions: list[BorderQueueDecision] = []
        for index, code in enumerate(codes):
            product_id = product_ids[index] if index < len(product_ids) else ""
            ignored_raw = ignored_flags[index] if index < len(ignored_flags) else "0"
            ignored = ignored_raw.strip() in {"1", "true", "on", "yes"}
            decisions.append(
                BorderQueueDecision(
                    ms_code=code,
                    domain_product_id=product_id.strip() or None,
                    ignored=ignored,
                )
            )
        try:
            apply_border_queue(
                tuple(decisions),
                products=store,
                border=border,
                lookup=lookup,
            )
        except DomainProductRejected as exc:
            message = str(exc) or "save_failed"
            return RedirectResponse(
                f"/admin/coffee-border-registration?error={quote(message)}",
                status_code=303,
            )
        return RedirectResponse("/admin/coffee-border-registration", status_code=303)
