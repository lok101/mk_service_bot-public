from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from beartype import beartype

from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage

MicromarketInventoryFormMode = Literal["now", "as_of"]

# Layout salt: pages by planogram shelves + off-planogram (not snack labels_v2).
INVENTORY_FORM_LAYOUT_SALT = "shelves_pages_v1"


@beartype
def inventory_form_fingerprint(
    *,
    pages: Sequence[InventoryFormPage],
    mode: MicromarketInventoryFormMode,
) -> str:
    """Canonical hash of page structure + inventory mode + shelves_pages_v1 salt.

    Display titles are intentionally excluded from the fingerprint.
    """
    payload = json.dumps(
        {
            "mode": mode,
            "pages": [
                {
                    "kit_group_id": page.kit_group_id,
                    "codes": list(page.product_codes),
                }
                for page in pages
            ],
            "layout": INVENTORY_FORM_LAYOUT_SALT,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
