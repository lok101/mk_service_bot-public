from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from beartype import beartype

from src.application.snack_loading.ports import InventoryFormCell

# Layout salt: readable titles/descriptions + qty validators (snack only).
INVENTORY_FORM_LAYOUT_SALT = "labels_v2"


@beartype
def inventory_form_fingerprint(cells: Sequence[InventoryFormCell]) -> str:
    """Canonical hash of (matrix, line, code) + layout salt (no display name)."""
    normalized = sorted(
        ([cell.matrix_name, cell.line_number, cell.product_code] for cell in cells),
        key=lambda item: (item[0], item[1], item[2]),
    )
    payload = json.dumps(
        {
            "cells": normalized,
            "layout": INVENTORY_FORM_LAYOUT_SALT,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
