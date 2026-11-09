from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from beartype import beartype

from src.application.snack_loading.form_fingerprint import inventory_form_fingerprint
from src.application.snack_loading.ports import (
    InventoryFormCell,
    SnackInventoryFormFactory,
    SnackInventoryFormMode,
    SnackInventoryFormRegistry,
    SnackInventoryFormsConfig,
)
from src.domain.form_tokens import (
    SnackInventoryFormPurpose,
    SnackInventoryFormTokenPayload,
    create_snack_inventory_form_token,
)
from src.domain.ids import TechnicianId
from src.domain.snack_loading.events import CellKey

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class IssuedSnackInventoryLink:
    form_id: str
    form_url: str
    fingerprint_id: str


@beartype
@dataclass(frozen=True, slots=True)
class IssueSnackInventoryLink:
    registry: SnackInventoryFormRegistry
    factory: SnackInventoryFormFactory
    forms_settings: SnackInventoryFormsConfig
    now_template_id: str
    as_of_template_id: str
    token_entry_id: str
    now_token_secret: str
    as_of_token_secret: str
    clock: Callable[[], datetime]
    qty_max: int

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: SnackInventoryFormMode,
        cells: Sequence[InventoryFormCell],
        technician_id: TechnicianId,
    ) -> IssuedSnackInventoryLink:
        self.forms_settings.require_snack_inventory_forms()
        if not self.token_entry_id.startswith("entry."):
            raise ValueError("Google Form token entry id must start with 'entry.'")

        fingerprint = inventory_form_fingerprint(cells)
        hit = self.registry.get(machine_code, mode, fingerprint)
        if hit is not None:
            _logger.info(
                "snack_inventory_form_fingerprint_hit",
                extra={
                    "machine_code": machine_code,
                    "mode": mode,
                    "fingerprint_id": fingerprint,
                    "form_id": hit.form_id,
                },
            )
            base_url = hit.form_url
            form_id = hit.form_id
        else:
            template_id = self.now_template_id if mode == "now" else self.as_of_template_id
            copied = self.factory.copy_template_and_build_questions(
                template_id=template_id,
                cells=cells,
                qty_max=self.qty_max,
            )
            self.registry.put(
                machine_code,
                mode,
                fingerprint,
                form_id=copied.form_id,
                form_url=copied.form_url,
            )
            _logger.info(
                "snack_inventory_form_fingerprint_miss",
                extra={
                    "machine_code": machine_code,
                    "mode": mode,
                    "fingerprint_id": fingerprint,
                    "form_id": copied.form_id,
                },
            )
            base_url = copied.form_url
            form_id = copied.form_id

        purpose: SnackInventoryFormPurpose = (
            "snack_inventory_now" if mode == "now" else "snack_inventory_as_of"
        )
        token_secret = self.now_token_secret if mode == "now" else self.as_of_token_secret
        cell_keys: tuple[CellKey, ...] = tuple(
            (machine_code, cell.matrix_name, cell.line_number) for cell in cells
        )
        product_codes = tuple(cell.product_code for cell in cells)
        token = create_snack_inventory_form_token(
            SnackInventoryFormTokenPayload(
                purpose=purpose,
                technician_id=technician_id,
                machine_code=machine_code,
                fingerprint_id=fingerprint,
                cell_keys=cell_keys,
                product_codes=product_codes,
                issued_at=self.clock(),
                nonce=secrets.token_urlsafe(12),
            ),
            token_secret,
        )
        return IssuedSnackInventoryLink(
            form_id=form_id,
            form_url=_prefilled_form_url(
                form_url=base_url,
                entry_id=self.token_entry_id,
                value=token,
            ),
            fingerprint_id=fingerprint,
        )


@beartype
def _prefilled_form_url(*, form_url: str, entry_id: str, value: str) -> str:
    if not form_url:
        raise ValueError("Google Form URL must not be empty")
    if not value:
        raise ValueError("Google Form prefilled value must not be empty")
    parts = urlsplit(form_url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params["usp"] = "pp_url"
    query_params[entry_id] = value
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query_params), parts.fragment),
    )


@beartype
def default_issue_clock() -> datetime:
    return datetime.now(tz=UTC)
