from __future__ import annotations

from src.interfaces.admin.user_facing_errors import admin_error_present


def test_admin_error_present_known_code() -> None:
    error = admin_error_present("order_recounted")
    assert error.code == "order_recounted"
    assert "пересчёт" in error.cause.casefold() or "пересчитан" in error.cause.casefold()
    assert error.action
    assert error.targets == ()


def test_admin_error_present_unknown_code_fallback() -> None:
    error = admin_error_present("totally_unknown_reason_xyz")
    assert error.code == "totally_unknown_reason_xyz"
    assert "не удалось" in error.cause.casefold()
    assert "код" in error.action.casefold() or "поддерж" in error.action.casefold()


def test_admin_error_present_qty_above_lists_targets() -> None:
    error = admin_error_present(
        "qty_above_available",
        targets=("SKU-B", "SKU-A"),
    )
    assert error.code == "qty_above_available"
    assert error.targets == ("SKU-A", "SKU-B")
    assert "SKU-A" in error.cause or "SKU-A" in error.action
    assert "SKU-B" in error.cause or "SKU-B" in error.action
