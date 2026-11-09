from __future__ import annotations

import logging

import pytest

from src.application.micromarket_loading.catalog_ensure import (
    CatalogCard,
    CatalogEnsureError,
    CatalogEnsureLine,
    CatalogEnsureOk,
    ensure_kit_shop_catalog_for_snapshot,
)


class _FakeCatalogWriter:
    def __init__(self, *, fail_on_vendor: str | None = None) -> None:
        self.adds: list[tuple[str, str]] = []
        self.edits: list[tuple[int, str]] = []
        self._next_id = 100
        self._fail_on_vendor = fail_on_vendor

    def add_product(self, *, vendor_code: str, product_name: str) -> int:
        if self._fail_on_vendor == vendor_code:
            raise RuntimeError(f"write failed for {vendor_code}")
        self.adds.append((vendor_code, product_name))
        product_id = self._next_id
        self._next_id += 1
        return product_id

    def edit_product_name(self, *, product_id: int, product_name: str) -> None:
        self.edits.append((product_id, product_name))


def test_ensure_noop_when_single_live_name_matches() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(CatalogEnsureLine(vendor_code="d-1001", domain_name="  Вода 0.5  "),),
        cards=(
            CatalogCard(
                product_id=20,
                vendor_code="d-1001",
                product_name=" Вода 0.5 ",
                is_deleted=False,
            ),
        ),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureOk)
    assert writer.adds == []
    assert writer.edits == []


def test_ensure_renames_when_single_live_name_differs() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(CatalogEnsureLine(vendor_code="d-1001", domain_name="  Вода 0.5л  "),),
        cards=(
            CatalogCard(
                product_id=20,
                vendor_code="d-1001",
                product_name="Вода старое",
                is_deleted=False,
            ),
        ),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureOk)
    assert writer.adds == []
    assert writer.edits == [(20, "Вода 0.5л")]


def test_ensure_creates_when_no_live_cards() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(CatalogEnsureLine(vendor_code="d-1001", domain_name="Вода 0.5"),),
        cards=(),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureOk)
    assert writer.adds == [("d-1001", "Вода 0.5")]
    assert writer.edits == []


def test_ensure_creates_when_only_deleted_cards() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(CatalogEnsureLine(vendor_code="d-1001", domain_name="Вода 0.5"),),
        cards=(
            CatalogCard(
                product_id=7,
                vendor_code="d-1001",
                product_name="Старое",
                is_deleted=True,
            ),
        ),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureOk)
    assert writer.adds == [("d-1001", "Вода 0.5")]
    assert writer.edits == []
    assert writer.adds[0][0] == "d-1001"
    # тот же ProductId=7 не восстанавливается — новый id из writer
    assert writer._next_id == 101


def test_ensure_errors_when_two_live_cards() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(CatalogEnsureLine(vendor_code="d-1001", domain_name="Вода"),),
        cards=(
            CatalogCard(20, "d-1001", "A", False),
            CatalogCard(21, "d-1001", "B", False),
        ),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureError)
    assert "d-1001" in result.message
    assert writer.adds == []
    assert writer.edits == []


def test_ensure_errors_when_domain_name_empty() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(CatalogEnsureLine(vendor_code="d-1001", domain_name="   "),),
        cards=(CatalogCard(20, "d-1001", "Вода", False),),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureError)
    assert "d-1001" in result.message
    assert writer.adds == []
    assert writer.edits == []


def test_ensure_stops_on_write_error_after_prior_success() -> None:
    writer = _FakeCatalogWriter(fail_on_vendor="d-1002")
    with pytest.raises(RuntimeError, match="write failed for d-1002"):
        ensure_kit_shop_catalog_for_snapshot(
            lines=(
                CatalogEnsureLine(vendor_code="d-1001", domain_name="Первый"),
                CatalogEnsureLine(vendor_code="d-1002", domain_name="Второй"),
            ),
            cards=(),
            writer=writer,
        )
    assert writer.adds == [("d-1001", "Первый")]
    assert writer.edits == []


def test_ensure_same_code_twice_does_not_create_twice() -> None:
    writer = _FakeCatalogWriter()
    result = ensure_kit_shop_catalog_for_snapshot(
        lines=(
            CatalogEnsureLine(vendor_code="d-1001", domain_name="Вода"),
            CatalogEnsureLine(vendor_code="d-1001", domain_name="Вода"),
        ),
        cards=(),
        writer=writer,
    )
    assert isinstance(result, CatalogEnsureOk)
    assert writer.adds == [("d-1001", "Вода")]
    assert writer.edits == []


def test_ensure_logs_code_action_and_product_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = _FakeCatalogWriter()
    cards = (
        CatalogCard(20, "d-noop", "Имя", False),
        CatalogCard(21, "d-rename", "Старое", False),
    )
    with caplog.at_level(logging.INFO, logger="src.application.micromarket_loading.catalog_ensure"):
        result = ensure_kit_shop_catalog_for_snapshot(
            lines=(
                CatalogEnsureLine("d-noop", "Имя"),
                CatalogEnsureLine("d-rename", "Новое"),
                CatalogEnsureLine("d-create", "Создать"),
            ),
            cards=cards,
            writer=writer,
        )
    assert isinstance(result, CatalogEnsureOk)

    def _extras(action: str) -> dict[str, object]:
        for record in caplog.records:
            if record.getMessage() != "kit_shop_catalog_ensure":
                continue
            payload = {
                "vendor_code": getattr(record, "vendor_code", record.__dict__.get("vendor_code")),
                "action": getattr(record, "action", record.__dict__.get("action")),
                "product_id": getattr(record, "product_id", record.__dict__.get("product_id")),
            }
            if payload["action"] == action:
                return payload
        raise AssertionError(f"log action={action!r} not found")

    assert _extras("noop") == {
        "vendor_code": "d-noop",
        "action": "noop",
        "product_id": 20,
    }
    assert _extras("rename") == {
        "vendor_code": "d-rename",
        "action": "rename",
        "product_id": 21,
    }
    create_extra = _extras("create")
    assert create_extra["vendor_code"] == "d-create"
    assert create_extra["action"] == "create"
    assert create_extra["product_id"] == 100
