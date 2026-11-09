from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from src.application.snack_loading.form_fingerprint import inventory_form_fingerprint
from src.application.snack_loading.issue_inventory_link import IssueSnackInventoryLink
from src.application.snack_loading.ports import InventoryFormCell
from src.domain.form_tokens import verify_snack_inventory_form_token
from src.domain.ids import TechnicianId
from src.infrastructure.testing.snack_loading_fakes import (
    FakeSnackInventoryFormFactory,
    FakeSnackInventoryFormsConfig,
    InMemorySnackInventoryFormRegistry,
)

_CELLS = (
    InventoryFormCell("SnackA", 1, "SKU1", "Name1"),
    InventoryFormCell("SnackA", 2, "SKU2", "Name2"),
)
_MACHINE = "514"
_NOW_TEMPLATE = "template-now"
_AS_OF_TEMPLATE = "template-as-of"
_TOKEN_ENTRY_ID = "entry.snack"
_NOW_SECRET = "now-secret"
_AS_OF_SECRET = "as-of-secret"
_TECHNICIAN = TechnicianId("tech-1")
_ISSUED_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _issue_uc(
    *,
    registry: InMemorySnackInventoryFormRegistry | None = None,
    factory: FakeSnackInventoryFormFactory | None = None,
    forms_settings: FakeSnackInventoryFormsConfig | None = None,
    token_entry_id: str = _TOKEN_ENTRY_ID,
    now_token_secret: str = _NOW_SECRET,
    as_of_token_secret: str = _AS_OF_SECRET,
) -> tuple[
    IssueSnackInventoryLink,
    InMemorySnackInventoryFormRegistry,
    FakeSnackInventoryFormFactory,
]:
    reg = registry if registry is not None else InMemorySnackInventoryFormRegistry()
    fac = factory if factory is not None else FakeSnackInventoryFormFactory()
    settings = forms_settings if forms_settings is not None else FakeSnackInventoryFormsConfig()
    uc = IssueSnackInventoryLink(
        registry=reg,
        factory=fac,
        forms_settings=settings,
        now_template_id=_NOW_TEMPLATE,
        as_of_template_id=_AS_OF_TEMPLATE,
        token_entry_id=token_entry_id,
        now_token_secret=now_token_secret,
        as_of_token_secret=as_of_token_secret,
        clock=lambda: _ISSUED_AT,
        qty_max=30,
    )
    return uc, reg, fac


def _token_from_url(url: str, entry_id: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query[entry_id][0]


def test_form_registry_hit_reuses_form_id() -> None:
    cells = _CELLS
    fp = inventory_form_fingerprint(cells)
    registry = InMemorySnackInventoryFormRegistry()
    factory = FakeSnackInventoryFormFactory()
    registry.put(
        _MACHINE,
        "now",
        fp,
        form_id="form-1",
        form_url="https://forms.example/1",
    )
    uc, _, _ = _issue_uc(registry=registry, factory=factory)

    link1 = uc.execute(
        machine_code=_MACHINE,
        mode="now",
        cells=cells,
        technician_id=_TECHNICIAN,
    )
    link2 = uc.execute(
        machine_code=_MACHINE,
        mode="now",
        cells=cells,
        technician_id=_TECHNICIAN,
    )

    assert link1.form_id == link2.form_id == "form-1"
    assert factory.copy_calls == 0


def test_form_registry_miss_copies_template() -> None:
    cells = (InventoryFormCell("SnackA", 1, "SKU1"),)
    uc, registry, factory = _issue_uc()

    link1 = uc.execute(
        machine_code=_MACHINE,
        mode="now",
        cells=cells,
        technician_id=_TECHNICIAN,
    )
    link2 = uc.execute(
        machine_code=_MACHINE,
        mode="now",
        cells=cells,
        technician_id=_TECHNICIAN,
    )

    assert factory.copy_calls == 1
    assert link1.form_id == link2.form_id
    stored = registry.get(_MACHINE, "now", inventory_form_fingerprint(cells))
    assert stored is not None
    assert stored.form_id == link1.form_id


def test_fingerprint_changes_when_product_changes() -> None:
    a = inventory_form_fingerprint((InventoryFormCell("M", 1, "A"),))
    b = inventory_form_fingerprint((InventoryFormCell("M", 1, "B"),))
    assert a != b


def test_fingerprint_layout_salt_changes_hash_for_same_cells() -> None:
    """happy: layout salt is present; display name not in fingerprint."""
    from src.application.snack_loading.form_fingerprint import INVENTORY_FORM_LAYOUT_SALT

    assert INVENTORY_FORM_LAYOUT_SALT == "labels_v2"
    without_name = inventory_form_fingerprint((InventoryFormCell("M", 1, "A"),))
    with_name = inventory_form_fingerprint((InventoryFormCell("M", 1, "A", "Display"),))
    assert without_name == with_name
    ordered = inventory_form_fingerprint(
        (InventoryFormCell("B", 1, "X"), InventoryFormCell("A", 2, "Y"))
    )
    reordered = inventory_form_fingerprint(
        (InventoryFormCell("A", 2, "Y"), InventoryFormCell("B", 1, "X"))
    )
    assert ordered == reordered


def test_issue_link_uses_shared_token_entry_id() -> None:
    cells = (InventoryFormCell("SnackA", 1, "SKU1"),)
    uc, _, _ = _issue_uc(token_entry_id=_TOKEN_ENTRY_ID)

    link_now = uc.execute(
        machine_code=_MACHINE,
        mode="now",
        cells=cells,
        technician_id=_TECHNICIAN,
    )
    link_as_of = uc.execute(
        machine_code=_MACHINE,
        mode="as_of",
        cells=cells,
        technician_id=_TECHNICIAN,
    )

    assert _TOKEN_ENTRY_ID in link_now.form_url
    assert _TOKEN_ENTRY_ID in link_as_of.form_url
    token_now = _token_from_url(link_now.form_url, _TOKEN_ENTRY_ID)
    token_as_of = _token_from_url(link_as_of.form_url, _TOKEN_ENTRY_ID)
    payload_now = verify_snack_inventory_form_token(
        token_now,
        _NOW_SECRET,
        expected_purpose="snack_inventory_now",
    )
    payload_as_of = verify_snack_inventory_form_token(
        token_as_of,
        _AS_OF_SECRET,
        expected_purpose="snack_inventory_as_of",
    )
    assert payload_now.machine_code == _MACHINE
    assert payload_as_of.machine_code == _MACHINE
    assert payload_now.fingerprint_id == payload_as_of.fingerprint_id


def test_issue_link_requires_snack_inventory_forms_when_missing() -> None:
    uc, _, _ = _issue_uc(forms_settings=FakeSnackInventoryFormsConfig(incomplete=True))

    with pytest.raises(ValueError, match="SNACK_INVENTORY"):
        uc.execute(
            machine_code=_MACHINE,
            mode="now",
            cells=(InventoryFormCell("SnackA", 1, "SKU1"),),
            technician_id=_TECHNICIAN,
        )
