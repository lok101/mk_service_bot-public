from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.ports import (
    CopiedMicromarketInventoryForm,
    MicromarketInventoryFormFactory,
)
from src.infrastructure.google_forms.inventory_qty_validation import (
    inventory_qty_validation_upper,
)


@beartype
@dataclass(frozen=True, slots=True)
class DriveMicromarketInventoryFormFactory(MicromarketInventoryFormFactory):
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
        pages: Sequence[InventoryFormPage],
        product_names: Mapping[str, str],
        qty_max: int,
    ) -> CopiedMicromarketInventoryForm:
        if not template_id:
            raise ValueError("Micromarket inventory form template_id must not be empty")
        if not pages:
            raise ValueError("Micromarket inventory form pages must not be empty")
        inventory_qty_validation_upper(qty_max)

        sku_count = sum(len(page.product_codes) for page in pages)
        body: dict[str, Any] = {
            "name": f"Micromarket inventory ({sku_count} SKUs)",
        }
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
            raise ValueError("Copied micromarket inventory form has no responder URL")
        form_url = responder_uri.strip()

        requests = _build_replace_questions_requests(
            pages=pages,
            product_names=product_names,
        )
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
                raise ValueError("Copied micromarket inventory form has no responder URL")
            form_url = published_uri.strip()

        return CopiedMicromarketInventoryForm(form_id=form_id, form_url=form_url)


@beartype
def _build_replace_questions_requests(
    *,
    pages: Sequence[InventoryFormPage],
    product_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build Forms batchUpdate requests for shelf pages.

    Google Forms already has section 1 (form info). A leading ``pageBreakItem``
    would create an empty first section; therefore the first non-empty page only
    sets ``info.title`` and adds questions, and page breaks start from page 2.
    """
    requests: list[dict[str, Any]] = []
    index = 0
    first_page = True
    for page in pages:
        if not page.product_codes:
            continue
        if first_page:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"title": page.title},
                        "updateMask": "title",
                    },
                },
            )
            first_page = False
        else:
            requests.append(
                {
                    "createItem": {
                        "item": {
                            "title": page.title,
                            "pageBreakItem": {},
                        },
                        "location": {"index": index},
                    },
                },
            )
            index += 1
        for product_code in page.product_codes:
            name = product_names.get(product_code, "").strip()
            title = name if name else product_code
            question: dict[str, Any] = {
                "required": True,
                "textQuestion": {"paragraph": False},
            }
            requests.append(
                {
                    "createItem": {
                        "item": {
                            "title": title,
                            "description": product_code,
                            "questionItem": {
                                "question": question,
                            },
                        },
                        "location": {"index": index},
                    },
                },
            )
            index += 1
    return requests
