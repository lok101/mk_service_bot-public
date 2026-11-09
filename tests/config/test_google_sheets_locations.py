from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.google_sheets import GoogleSheetsSettings


def test_coffee_env_aliases_renamed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COFFEE_TECHNICIAN_LOCATIONS_SPREADSHEET_ID", "ss-coffee")
    monkeypatch.setenv("COFFEE_TECHNICIAN_LOCATIONS_SHEET_ID", "1")
    monkeypatch.setenv("USERS_SHEET_ID", "2")
    s = GoogleSheetsSettings()
    assert s.coffee_technician_locations_spreadsheet_id == "ss-coffee"
    assert s.coffee_technician_locations_sheet_id == 1
    assert s.is_coffee_technician_locations_configured is True


def test_coffee_locations_triple_all_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COFFEE_TECHNICIAN_LOCATIONS_SPREADSHEET_ID", "ss")
    monkeypatch.setenv("COFFEE_TECHNICIAN_LOCATIONS_SHEET_ID", "1")
    # USERS_SHEET_ID omitted
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()


def test_snack_locations_pair_both_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNACK_TECHNICIAN_LOCATIONS_SPREADSHEET_ID", "ss-snack")
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()


def test_snack_locations_pair_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNACK_TECHNICIAN_LOCATIONS_SPREADSHEET_ID", "ss-snack")
    monkeypatch.setenv("SNACK_TECHNICIAN_LOCATIONS_SHEET_ID", "9")
    s = GoogleSheetsSettings()
    assert s.is_snack_technician_locations_configured is True
    assert s.snack_technician_locations_sheet_id == 9


def test_legacy_technician_locations_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TECHNICIAN_LOCATIONS_SPREADSHEET_ID", "legacy")
    monkeypatch.setenv("LOCATIONS_SHEET_ID", "1")
    s = GoogleSheetsSettings()
    assert s.coffee_technician_locations_spreadsheet_id == ""
    assert s.is_coffee_technician_locations_configured is False


def test_technicians_directory_pair_both_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TECHNICIANS_DIRECTORY_SPREADSHEET_ID", "ss-tech")
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()


def test_technicians_directory_pair_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TECHNICIANS_DIRECTORY_SPREADSHEET_ID", "ss-tech")
    monkeypatch.setenv("TECHNICIANS_DIRECTORY_SHEET_ID", "7")
    s = GoogleSheetsSettings()
    assert s.is_technicians_directory_configured is True
    assert s.technicians_directory_spreadsheet_id == "ss-tech"
    assert s.technicians_directory_sheet_id == 7


def test_technicians_directory_sheet_id_is_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TECHNICIANS_DIRECTORY_SPREADSHEET_ID", "ss-tech")
    monkeypatch.setenv("TECHNICIANS_DIRECTORY_SHEET_ID", "7")
    s = GoogleSheetsSettings()
    assert isinstance(s.technicians_directory_sheet_id, int)


def test_prod_validation_requires_technicians_directory() -> None:
    from tests.infrastructure.test_runtime_validation import (
        _google_sheets_settings,
        _prod_settings,
    )

    from src.infrastructure.composition.validation import validate_runtime_settings

    settings = _prod_settings(
        google_sheets=_google_sheets_settings(
            technicians_directory_spreadsheet_id="",
            technicians_directory_sheet_id=None,
        ),
    )
    with pytest.raises(ValueError, match="TECHNICIANS_DIRECTORY"):
        validate_runtime_settings(settings)


def test_locations_directory_pair_both_or_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCATIONS_DIRECTORY_SPREADSHEET_ID", "ss-loc")
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()


def test_locations_directory_sheet_without_spreadsheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCATIONS_DIRECTORY_SHEET_ID", "11")
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()


def test_locations_directory_pair_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCATIONS_DIRECTORY_SPREADSHEET_ID", "ss-loc")
    monkeypatch.setenv("LOCATIONS_DIRECTORY_SHEET_ID", "11")
    s = GoogleSheetsSettings()
    assert s.is_locations_directory_configured is True
    assert s.locations_directory_spreadsheet_id == "ss-loc"
    assert s.locations_directory_sheet_id == 11


def test_locations_directory_sheet_id_is_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCATIONS_DIRECTORY_SPREADSHEET_ID", "ss-loc")
    monkeypatch.setenv("LOCATIONS_DIRECTORY_SHEET_ID", "11")
    s = GoogleSheetsSettings()
    assert isinstance(s.locations_directory_sheet_id, int)


def test_locations_directory_pair_omitted_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCATIONS_DIRECTORY_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("LOCATIONS_DIRECTORY_SHEET_ID", raising=False)
    s = GoogleSheetsSettings()
    assert s.is_locations_directory_configured is False
    assert s.locations_directory_sheet_id is None


def test_prod_validation_does_not_require_locations_directory() -> None:
    from tests.infrastructure.test_runtime_validation import (
        _google_sheets_settings,
        _prod_settings,
    )

    from src.infrastructure.composition.validation import validate_runtime_settings

    settings = _prod_settings(
        google_sheets=_google_sheets_settings(
            locations_directory_spreadsheet_id="",
            locations_directory_sheet_id=None,
        ),
    )
    validate_runtime_settings(settings)
