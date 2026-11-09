from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.snack_loading.ports import (
    CopiedSnackInventoryForm,
    InventoryFormCell,
    SnackInventoryFormFactory,
)
from src.infrastructure.google_forms.inventory_qty_validation import (
    inventory_qty_validation_upper,
)


@beartype
@dataclass(frozen=True, slots=True)
class DriveSnackInventoryFormFactory(SnackInventoryFormFactory):
    """Copy a Google Form template via Drive and replace questions via Forms API.

    ``drive_files_copy`` / ``forms_batch_update`` are injectable callables so unit
    tests can fake the Google client without network.
    """

    drive_files_copy: Callable[..., dict[str, Any]]
    forms_batch_update: Callable[..., dict[str, Any]]
    forms_get: Callable[..., dict[str, Any]]
    forms_set_publish_settings: Callable[..., dict[str, Any]]
    qty_max: int
    copy_folder_id: str | None = None

    @beartype
    def copy_template_and_build_questions(
        self,
        *,
        template_id: str,
        cells: Sequence[InventoryFormCell],
        qty_max: int,
    ) -> CopiedSnackInventoryForm:
        if not template_id:
            raise ValueError("Snack inventory form template_id must not be empty")
        if not cells:
            raise ValueError("Snack inventory form cells must not be empty")
        inventory_qty_validation_upper(qty_max)

        body: dict[str, Any] = {"name": f"Snack inventory ({len(cells)} cells)"}
        if self.copy_folder_id is not None:
            body["parents"] = [self.copy_folder_id]
        copied = self.drive_files_copy(
            fileId=template_id,
            body=body,
            fields="id",
            supportsAllDrives=True,
        )
        form_id = str(copied["id"])
        meta = self.forms_get(formId=form_id)
        responder_uri = meta.get("responderUri")
        if not isinstance(responder_uri, str) or not responder_uri.strip():
            raise ValueError("Copied snack inventory form has no responder URL")
        form_url = responder_uri.strip()

        requests = _build_replace_questions_requests(cells=cells)
        if requests:
            self.forms_batch_update(formId=form_id, body={"requests": requests})

        if "publishSettings" in meta:
            self.forms_set_publish_settings(
                formId=form_id,
                body={
                    "publishSettings": {
                        "publishState": {
                            "isPublished": True,
                            "isAcceptingResponses": True,
                        }
                    }
                },
            )
            published_meta = self.forms_get(formId=form_id)
            published_uri = published_meta.get("responderUri")
            if not isinstance(published_uri, str) or not published_uri.strip():
                raise ValueError("Copied snack inventory form has no responder URL")
            form_url = published_uri.strip()

        return CopiedSnackInventoryForm(form_id=form_id, form_url=form_url)


@beartype
def _build_replace_questions_requests(
    *,
    cells: Sequence[InventoryFormCell],
) -> list[dict[str, Any]]:
    """Build Forms API requests: one qty question per cell (name title, identity desc)."""
    requests: list[dict[str, Any]] = []
    for index, cell in enumerate(cells):
        identity = f"{cell.matrix_name} / #{cell.line_number} / {cell.product_code}"
        title = cell.product_name.strip() if cell.product_name.strip() else cell.product_code
        question: dict[str, Any] = {
            "required": True,
            "textQuestion": {"paragraph": False},
        }
        requests.append(
            {
                "createItem": {
                    "item": {
                        "title": title,
                        "description": identity,
                        "questionItem": {
                            "question": question,
                        },
                    },
                    "location": {"index": index},
                },
            },
        )
    return requests
