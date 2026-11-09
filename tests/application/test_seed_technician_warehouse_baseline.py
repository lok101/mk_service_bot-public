from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

import pytest

from src.application.technician_warehouse.errors import (
    SeedWarehouseBaselineError,
    SeedWarehouseBaselinePartialWriteError,
)
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.seed_baseline import SeedTechnicianWarehouseBaseline
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECH_A = TechnicianId("10003")
_TECH_B = TechnicianId("10004")
_COUNTED_AT = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class _FakeCatalog:
    mapping: dict[str, str]

    def code_to_name(self) -> dict[str, str]:
        return dict(self.mapping)


def _build_uc(
    *,
    catalog: _FakeCatalog | None = None,
    event_store: InMemoryTechnicianWarehouseEventStore | None = None,
) -> tuple[SeedTechnicianWarehouseBaseline, InMemoryTechnicianWarehouseEventStore]:
    store = event_store or InMemoryTechnicianWarehouseEventStore()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    executor = TechnicianWarehouseExecutor(repository=repo, publisher=None)
    uc = SeedTechnicianWarehouseBaseline(
        executor=executor,
        event_store=store,
        catalog=catalog or _FakeCatalog({"999": "Кофе", "1001": "Стакан"}),
    )
    return uc, store


def test_write_template_emits_all_catalog_skus_with_null_stock(tmp_path: Path) -> None:
    uc, _ = _build_uc()
    out = tmp_path / "baseline.json"
    uc.write_template(technician_ids=("10003", "10004"), output_path=out)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM for Windows editors"
    payload = json.loads(out.read_text(encoding="utf-8-sig"))
    assert payload == {
        "technicians": [
            {
                "technician_id": "10003",
                "counted_at": None,
                "stocks": [
                    {"product_code": "1001", "product_name": "Стакан", "stock": None},
                    {"product_code": "999", "product_name": "Кофе", "stock": None},
                ],
            },
            {
                "technician_id": "10004",
                "counted_at": None,
                "stocks": [
                    {"product_code": "1001", "product_name": "Стакан", "stock": None},
                    {"product_code": "999", "product_name": "Кофе", "stock": None},
                ],
            },
        ],
    }


def _valid_file_payload(*, technician_id: str = "10003", stock: object = 252) -> dict:
    return {
        "technicians": [
            {
                "technician_id": technician_id,
                "counted_at": "2026-06-01T00:00:00+00:00",
                "stocks": [
                    {"product_code": "999", "product_name": "ignored", "stock": stock},
                    {"product_code": "1001", "product_name": "ignored", "stock": 0},
                ],
            }
        ]
    }


def test_validate_rejects_catalog_and_stock_errors(tmp_path: Path) -> None:
    uc, _ = _build_uc()
    cases: list[tuple[str, dict, str]] = [
        ("empty technicians", {"technicians": []}, "technicians"),
        (
            "null stock",
            {
                "technicians": [
                    {
                        "technician_id": "10003",
                        "counted_at": "2026-06-01T00:00:00+00:00",
                        "stocks": [
                            {"product_code": "999", "product_name": "x", "stock": None},
                            {"product_code": "1001", "product_name": "x", "stock": 1},
                        ],
                    }
                ]
            },
            "null",
        ),
        ("negative stock", _valid_file_payload(stock=-1), ">= 0"),
        (
            "missing catalog SKU",
            {
                "technicians": [
                    {
                        "technician_id": "10003",
                        "counted_at": "2026-06-01T00:00:00+00:00",
                        "stocks": [
                            {"product_code": "999", "product_name": "x", "stock": 1},
                        ],
                    }
                ]
            },
            "missing catalog SKU",
        ),
        (
            "unknown code",
            {
                "technicians": [
                    {
                        "technician_id": "10003",
                        "counted_at": "2026-06-01T00:00:00+00:00",
                        "stocks": [
                            {"product_code": "999", "product_name": "x", "stock": 1},
                            {"product_code": "1001", "product_name": "x", "stock": 1},
                            {"product_code": "ghost", "product_name": "x", "stock": 1},
                        ],
                    }
                ]
            },
            "ghost",
        ),
        (
            "duplicate code",
            {
                "technicians": [
                    {
                        "technician_id": "10003",
                        "counted_at": "2026-06-01T00:00:00+00:00",
                        "stocks": [
                            {"product_code": "999", "product_name": "x", "stock": 1},
                            {"product_code": "999", "product_name": "x", "stock": 2},
                            {"product_code": "1001", "product_name": "x", "stock": 1},
                        ],
                    }
                ]
            },
            "duplicate",
        ),
        (
            "naive counted_at",
            {
                "technicians": [
                    {
                        "technician_id": "10003",
                        "counted_at": "2026-06-01T00:00:00",
                        "stocks": [
                            {"product_code": "999", "product_name": "x", "stock": 1},
                            {"product_code": "1001", "product_name": "x", "stock": 1},
                        ],
                    }
                ]
            },
            "timezone-aware",
        ),
        (
            "bad stock type",
            _valid_file_payload(stock="not-a-number"),
            "not a number",
        ),
    ]
    for label, payload, match in cases:
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SeedWarehouseBaselineError, match=match):
            uc.dry_run(path)


def test_validate_accepts_zero_and_numeric_string_stock(tmp_path: Path) -> None:
    uc, _ = _build_uc()
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(_valid_file_payload(stock="252")), encoding="utf-8")
    report = uc.dry_run(path)
    assert report.ok_technician_ids == ("10003",)
    assert report.issues == ()


def _append_loading(
    store: InMemoryTechnicianWarehouseEventStore,
    *,
    technician_id: TechnicianId,
    submitted_at: datetime,
) -> None:
    store.append(
        technician_id,
        0,
        (
            TechnicianWarehouseLoadingObserved(
                event_id=EventId("load-1"),
                technician_id=technician_id,
                occurred_at=submitted_at,
                source_event_id="src-1",
                machine_id=MachineId("vm-01"),
                submitted_at=submitted_at,
                lines=(TechnicianWarehouseLine(sku="999", quantity_base=Decimal("1")),),
            ),
        ),
    )


def _append_transfer(
    store: InMemoryTechnicianWarehouseEventStore,
    *,
    technician_id: TechnicianId,
    moment: datetime,
    document_id: str = "ms-1",
    voided: bool = False,
) -> None:
    events = [
        TechnicianWarehouseTransferObserved(
            event_id=EventId(f"tr-{document_id}"),
            technician_id=technician_id,
            occurred_at=moment,
            external_document_id=document_id,
            moment=moment,
            updated_at=moment,
            observed_at=moment,
            content_hash="h1",
            direction=TransferDirection.SUPPLY_IN,
            lines=(TechnicianWarehouseLine(sku="999", quantity_base=Decimal("1")),),
        )
    ]
    if voided:
        events.append(
            TechnicianWarehouseTransferVoided(
                event_id=EventId(f"void-{document_id}"),
                technician_id=technician_id,
                occurred_at=moment,
                external_document_id=document_id,
                previous_content_hash="h1",
                observed_at=moment,
            )
        )
    store.append(technician_id, 0, tuple(events))


def test_validate_rejects_when_inventory_already_exists(tmp_path: Path) -> None:
    uc, _ = _build_uc()
    path = tmp_path / "f.json"
    path.write_text(json.dumps(_valid_file_payload()), encoding="utf-8")
    uc.confirm(path)
    with pytest.raises(SeedWarehouseBaselineError, match="inventory"):
        uc.dry_run(path)


def test_confirm_rejects_loading_at_or_before_counted_at(tmp_path: Path) -> None:
    uc, store = _build_uc()
    _append_loading(store, technician_id=_TECH_A, submitted_at=_COUNTED_AT)
    path = tmp_path / "f.json"
    path.write_text(json.dumps(_valid_file_payload()), encoding="utf-8")
    with pytest.raises(SeedWarehouseBaselineError, match="loading"):
        uc.confirm(path)
    assert not any(
        isinstance(e, TechnicianWarehouseInventoryCounted)
        for e in store.get_events_for_technician(_TECH_A)
    )


def test_confirm_rejects_non_voided_transfer_at_or_before_counted_at(
    tmp_path: Path,
) -> None:
    uc, store = _build_uc()
    _append_transfer(store, technician_id=_TECH_A, moment=_COUNTED_AT, voided=False)
    path = tmp_path / "f.json"
    path.write_text(json.dumps(_valid_file_payload()), encoding="utf-8")
    with pytest.raises(SeedWarehouseBaselineError, match="transfer"):
        uc.confirm(path)
    assert not any(
        isinstance(e, TechnicianWarehouseInventoryCounted)
        for e in store.get_events_for_technician(_TECH_A)
    )


def test_confirm_allows_voided_transfer_at_or_before_counted_at(tmp_path: Path) -> None:
    uc, store = _build_uc()
    _append_transfer(store, technician_id=_TECH_A, moment=_COUNTED_AT, voided=True)
    path = tmp_path / "f.json"
    path.write_text(json.dumps(_valid_file_payload()), encoding="utf-8")
    result = uc.confirm(path)
    assert result.seeded_technician_ids == ("10003",)
    events = store.get_events_for_technician(_TECH_A)
    inv = next(e for e in events if isinstance(e, TechnicianWarehouseInventoryCounted))
    assert inv.baseline is True


def test_confirm_writes_baseline_inventory_event(tmp_path: Path) -> None:
    uc, store = _build_uc()
    path = tmp_path / "f.json"
    path.write_text(json.dumps(_valid_file_payload()), encoding="utf-8")
    result = uc.confirm(path)
    assert result.seeded_technician_ids == ("10003",)
    events = store.get_events_for_technician(_TECH_A)
    inv = next(e for e in events if isinstance(e, TechnicianWarehouseInventoryCounted))
    assert inv.baseline is True
    assert inv.counted_at == _COUNTED_AT
    assert inv.form_token == f"seed:10003:{_COUNTED_AT.isoformat()}"
    assert inv.inventory_id == inv.form_token
    assert dict(inv.lines)["999"] == Decimal("252")
    assert dict(inv.lines)["1001"] == Decimal("0")


def test_confirm_succeeds_without_publisher(tmp_path: Path) -> None:
    """Event-only: executor built with publisher=None must still seed."""
    uc, store = _build_uc()  # publisher=None inside _build_uc
    path = tmp_path / "f.json"
    path.write_text(json.dumps(_valid_file_payload()), encoding="utf-8")
    uc.confirm(path)
    assert any(
        isinstance(e, TechnicianWarehouseInventoryCounted)
        for e in store.get_events_for_technician(_TECH_A)
    )


def test_confirm_writes_nothing_when_second_technician_invalid(tmp_path: Path) -> None:
    uc, store = _build_uc()
    payload = {
        "technicians": [
            _valid_file_payload()["technicians"][0],
            {
                "technician_id": "10004",
                "counted_at": "2026-06-01T00:00:00+00:00",
                "stocks": [
                    {"product_code": "999", "product_name": "x", "stock": 1},
                    # missing 1001 → fail after tech A would have been valid alone
                ],
            },
        ]
    }
    path = tmp_path / "multi.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SeedWarehouseBaselineError):
        uc.confirm(path)
    assert store.get_events_for_technician(_TECH_A) == []
    assert store.get_events_for_technician(_TECH_B) == []


def test_confirm_reports_written_ids_on_mid_write_infra_failure(tmp_path: Path) -> None:
    store = InMemoryTechnicianWarehouseEventStore()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    real = TechnicianWarehouseExecutor(repository=repo, publisher=None)
    calls = {"n": 0}

    class _FailOnSecond:
        def execute(
            self,
            technician_id: TechnicianId,
            command: Callable[[TechnicianWarehouse], T],
        ) -> T:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("boom")
            return real.execute(technician_id, command)

    uc = SeedTechnicianWarehouseBaseline(
        executor=_FailOnSecond(),  # type: ignore[arg-type]
        event_store=store,
        catalog=_FakeCatalog({"999": "Кофе", "1001": "Стакан"}),
    )
    payload = {
        "technicians": [
            _valid_file_payload(technician_id="10003")["technicians"][0],
            _valid_file_payload(technician_id="10004")["technicians"][0],
        ]
    }
    path = tmp_path / "multi.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SeedWarehouseBaselinePartialWriteError) as exc_info:
        uc.confirm(path)
    assert exc_info.value.written_technician_ids == ("10003",)
    assert any(
        isinstance(e, TechnicianWarehouseInventoryCounted)
        for e in store.get_events_for_technician(_TECH_A)
    )
    assert not any(
        isinstance(e, TechnicianWarehouseInventoryCounted)
        for e in store.get_events_for_technician(_TECH_B)
    )
