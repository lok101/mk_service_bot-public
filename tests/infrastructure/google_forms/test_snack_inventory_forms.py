from __future__ import annotations

from typing import Any

import pytest

from src.application.snack_loading.ports import InventoryFormCell
from src.infrastructure.google_forms.inventory_qty_validation import (
    inventory_qty_validation_upper,
)
from src.infrastructure.google_forms.snack_inventory_forms import DriveSnackInventoryFormFactory

_CELLS = (InventoryFormCell("SnackA", 1, "SKU1", "Chips"),)
_FORM_ID = "form-copied-1"
_EDIT_URL = f"https://docs.google.com/forms/d/{_FORM_ID}/edit"
_RESPONDER_URL = f"https://docs.google.com/forms/d/{_FORM_ID}/viewform"
_PUBLISHED_URL = f"https://docs.google.com/forms/d/{_FORM_ID}/viewform?pub=1"
_QTY_MAX = 30
_PUBLISH_BODY = {
    "publishSettings": {
        "publishState": {
            "isPublished": True,
            "isAcceptingResponses": True,
        }
    }
}


def _noop_set_publish(**kwargs: Any) -> dict[str, Any]:
    del kwargs
    return {}


def _factory(**kwargs: Any) -> DriveSnackInventoryFormFactory:
    defaults: dict[str, Any] = {
        "drive_files_copy": lambda **_: {"id": _FORM_ID},
        "forms_batch_update": lambda **_: {},
        "forms_get": lambda **_: {"responderUri": _RESPONDER_URL},
        "forms_set_publish_settings": _noop_set_publish,
        "qty_max": _QTY_MAX,
    }
    defaults.update(kwargs)
    return DriveSnackInventoryFormFactory(**defaults)


def _copy(
    factory: DriveSnackInventoryFormFactory,
    *,
    cells: tuple[InventoryFormCell, ...] = _CELLS,
) -> Any:
    return factory.copy_template_and_build_questions(
        template_id="template-now",
        cells=cells,
        qty_max=_QTY_MAX,
    )


def test_drive_factory_stores_responder_uri_not_webview_link() -> None:
    calls: list[str] = []

    def drive_files_copy(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("copy")
        return {"id": _FORM_ID, "webViewLink": _EDIT_URL}

    def forms_get(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["formId"] == _FORM_ID
        calls.append("get")
        return {"responderUri": _RESPONDER_URL}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("batch")
        return {}

    factory = _factory(
        drive_files_copy=drive_files_copy,
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
    )
    copied = _copy(factory)
    assert copied.form_id == _FORM_ID
    assert copied.form_url == _RESPONDER_URL
    assert _EDIT_URL not in copied.form_url
    assert "get" in calls


def test_drive_factory_raises_when_responder_uri_missing() -> None:
    factory = _factory(
        drive_files_copy=lambda **_: {"id": _FORM_ID, "webViewLink": _EDIT_URL},
        forms_get=lambda **_: {},
    )
    with pytest.raises(ValueError, match="responder"):
        _copy(factory)


def test_drive_factory_copy_includes_parents_when_folder_set() -> None:
    captured: dict[str, Any] = {}

    def drive_files_copy(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": _FORM_ID}

    factory = _factory(drive_files_copy=drive_files_copy, copy_folder_id="folder-1")
    _copy(factory)
    assert captured["body"]["parents"] == ["folder-1"]


def test_drive_factory_copy_omits_parents_when_folder_unset() -> None:
    captured: dict[str, Any] = {}

    def drive_files_copy(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": _FORM_ID}

    factory = _factory(drive_files_copy=drive_files_copy)
    _copy(factory)
    assert "parents" not in captured["body"]


def test_snack_factory_publishes_when_publish_settings_present() -> None:
    calls: list[str] = []
    publish_captured: dict[str, Any] = {}
    get_count = 0

    def forms_get(**kwargs: Any) -> dict[str, Any]:
        nonlocal get_count
        assert kwargs["formId"] == _FORM_ID
        get_count += 1
        calls.append(f"get{get_count}")
        if get_count == 1:
            return {
                "responderUri": _RESPONDER_URL,
                "publishSettings": {"publishState": {"isPublished": False}},
            }
        return {"responderUri": _PUBLISHED_URL}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("batch")
        return {}

    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        publish_captured.update(kwargs)
        calls.append("publish")
        return {}

    factory = _factory(
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
        forms_set_publish_settings=forms_set_publish_settings,
    )
    copied = _copy(factory)
    assert copied.form_id == _FORM_ID
    assert copied.form_url == _PUBLISHED_URL
    assert publish_captured["formId"] == _FORM_ID
    assert publish_captured["body"] == _PUBLISH_BODY
    assert calls == ["get1", "batch", "publish", "get2"]


def test_snack_factory_skips_publish_when_publish_settings_absent() -> None:
    calls: list[str] = []

    def forms_get(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("get")
        return {"responderUri": _RESPONDER_URL}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("batch")
        return {}

    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append("publish")
        return {}

    factory = _factory(
        forms_batch_update=forms_batch_update,
        forms_get=forms_get,
        forms_set_publish_settings=forms_set_publish_settings,
    )
    copied = _copy(factory)
    assert copied.form_url == _RESPONDER_URL
    assert "publish" not in calls
    assert calls == ["get", "batch"]


def test_snack_factory_raises_when_set_publish_fails() -> None:
    def forms_set_publish_settings(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise RuntimeError("publish failed")

    factory = _factory(
        forms_get=lambda **_: {
            "responderUri": _RESPONDER_URL,
            "publishSettings": {},
        },
        forms_set_publish_settings=forms_set_publish_settings,
    )
    with pytest.raises(RuntimeError, match="publish failed"):
        _copy(factory)


def test_snack_factory_sets_title_description_without_forms_validation() -> None:
    """happy: title=name, description=matrix/#line/code; no Forms REST validation."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory)
    item = captured["body"]["requests"][0]["createItem"]["item"]
    assert item["title"] == "Chips"
    assert item["description"] == "SnackA / #1 / SKU1"
    question = item["questionItem"]["question"]
    assert question["required"] is True
    assert "validation" not in question
    assert inventory_qty_validation_upper(factory.qty_max) == _QTY_MAX


def test_snack_factory_falls_back_to_code_when_product_name_empty() -> None:
    """edge: empty product_name → title=code."""
    captured: dict[str, Any] = {}

    def forms_batch_update(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    factory = _factory(forms_batch_update=forms_batch_update)
    _copy(factory, cells=(InventoryFormCell("SnackA", 1, "SKU1", ""),))
    item = captured["body"]["requests"][0]["createItem"]["item"]
    assert item["title"] == "SKU1"
    assert item["description"] == "SnackA / #1 / SKU1"
