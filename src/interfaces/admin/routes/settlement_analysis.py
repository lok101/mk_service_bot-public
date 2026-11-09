from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.technician_settlement import (
    SettlementAnalysisPrefs,
    format_analysis_rubles,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    require_panel,
)
from src.interfaces.admin.page_builders import build_settlement_analysis_page_sync
from src.interfaces.admin.routes.master_data_park import _optional_decimal

_LOGGER = logging.getLogger(__name__)
_TEMPLATES.env.filters["analysis_rubles"] = format_analysis_rubles
_SETTLEMENT_ANALYSIS_PATH = "/admin/settlement-analysis"

__all__ = ["register_settlement_analysis_routes"]


@beartype
def register_settlement_analysis_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    if not deps.settlement_analysis_enabled:
        return

    @router.get("/settlement-analysis")
    async def settlement_analysis_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.SETTLEMENT_ANALYSIS)
        if isinstance(actor, Response):
            return actor
        if (
            deps.build_settlement_analysis_tree is None
            or deps.aggregate_settlement_clusters is None
            or deps.settlement_analysis_prefs_store is None
        ):
            return Response(status_code=404)
        payload = await asyncio.to_thread(
            build_settlement_analysis_page_sync,
            deps,
            actor_telegram_user_id=actor,
            technician_raw=request.query_params.get("technician_id", "").strip(),
            sessions_raw=request.query_params.get("sessions", "").strip(),
        )
        if payload.status_code != 200:
            return Response(status_code=payload.status_code)
        return _TEMPLATES.TemplateResponse(
            request,
            "settlement_analysis.html",
            page_context(request, deps, **payload.template_kwargs),
        )

    @router.post("/settlement-analysis/prefs")
    async def settlement_analysis_prefs_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.SETTLEMENT_ANALYSIS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_settlement_analysis_origin_reject")
            return Response(status_code=403)
        store = deps.settlement_analysis_prefs_store
        if store is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        prefs = _prefs_from_form(fields)
        store.save(actor, prefs)
        _LOGGER.info(
            "admin_settlement_analysis_prefs_save",
            extra={
                "telegram_user_id": actor,
                "price_count": len(prefs.unit_prices),
            },
        )
        technician_id = fields.get("technician_id", "").strip()
        sessions = fields.get("sessions", "").strip()
        target = _SETTLEMENT_ANALYSIS_PATH
        query_parts: list[str] = []
        if technician_id:
            query_parts.append(f"technician_id={technician_id}")
        if sessions:
            query_parts.append(f"sessions={sessions}")
        if query_parts:
            target = f"{target}?{'&'.join(query_parts)}"
        return RedirectResponse(target, status_code=303)

    @router.get("/settlement-analysis/sessions/{session_id}")
    async def settlement_analysis_session_get(
        request: Request,
        session_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.SETTLEMENT_ANALYSIS)
        if isinstance(actor, Response):
            return actor
        builder = deps.build_session_analysis_view
        if builder is None:
            return Response(status_code=404)
        technician_raw = request.query_params.get("technician_id", "").strip()
        if not technician_raw:
            return Response(status_code=404)
        try:
            technician_id = TechnicianId(technician_raw)
        except ValueError:
            return Response(status_code=404)
        view = builder.execute(technician_id=technician_id, session_id=session_id)
        if view is None:
            return Response(status_code=404)
        return _TEMPLATES.TemplateResponse(
            request,
            "settlement_analysis_session.html",
            page_context(
                request,
                deps,
                view=view,
                technician_id=technician_raw,
            ),
        )

    @router.get("/settlement-analysis/periods/{period_id}")
    async def settlement_analysis_period_get(
        request: Request,
        period_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.SETTLEMENT_ANALYSIS)
        if isinstance(actor, Response):
            return actor
        builder = deps.build_period_analysis_view
        if builder is None:
            return Response(status_code=404)
        view = builder.execute(period_id)
        if view is None:
            return Response(status_code=404)
        return _TEMPLATES.TemplateResponse(
            request,
            "settlement_analysis_period.html",
            page_context(request, deps, view=view),
        )


def _prefs_from_form(fields: dict[str, str]) -> SettlementAnalysisPrefs:
    unit_prices: dict[str, Decimal] = {}
    recoverable: set[str] = set()
    for key, raw in fields.items():
        if key.startswith("prices[") and key.endswith("]"):
            code = key[len("prices[") : -1].strip()
            if not code:
                continue
            value = raw.strip()
            if not value:
                continue
            try:
                parsed = _optional_decimal(value)
            except ValueError:
                continue
            if parsed is None:
                continue
            unit_prices[code] = parsed
        elif key.startswith("recoverable[") and key.endswith("]"):
            code = key[len("recoverable[") : -1].strip()
            if code and raw.strip():
                recoverable.add(code)
        elif key == "recoverable" and raw.strip():
            recoverable.add(raw.strip())
    loss_raw = fields.get("allowed_loss_pct", "").strip()
    allowed_loss_pct = Decimal("0")
    if loss_raw:
        try:
            parsed_loss = _optional_decimal(loss_raw)
        except ValueError:
            parsed_loss = Decimal("0")
        if parsed_loss is not None:
            allowed_loss_pct = parsed_loss
    return SettlementAnalysisPrefs(
        unit_prices=unit_prices,
        recoverable_product_codes=frozenset(recoverable),
        allowed_loss_pct=allowed_loss_pct,
    )
