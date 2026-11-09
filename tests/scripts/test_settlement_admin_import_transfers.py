from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from scripts.settlement_admin_lib.main import main

from src.application.technician_warehouse import (
    ImportedTransferRef,
    TechnicianWarehouseImportResult,
)
from src.domain.ids import TechnicianId

_ANCHOR_DT = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


@dataclass
class _FakeImporter:
    calls: list[tuple[str, datetime]] = field(default_factory=list)
    results: dict[str, TechnicianWarehouseImportResult] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)

    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        self.calls.append((technician_id.value, anchor_at))
        if technician_id.value in self.errors:
            raise self.errors[technician_id.value]
        return self.results.get(
            technician_id.value,
            TechnicianWarehouseImportResult(
                imported=1,
                updated=0,
                voided=0,
                ignored=0,
                skipped_unresolved=0,
                truncated_non_domain=0,
                transfer_refs=tuple(ImportedTransferRef(f"doc-{i}", f"h-{i}") for i in range(25)),
                unmatched_products=(),
            ),
        )


def _deps(*, importer, warehouse_repository, event_store=None):
    return SimpleNamespace(
        import_transfers=importer,
        warehouse_repository=warehouse_repository,
        warehouse_event_store=event_store,
    )


@dataclass
class _OpenRepo:
    closed_ids: frozenset[str] = frozenset()
    inventory_by_tech: dict[str, datetime] | None = None

    def get(self, technician_id: TechnicianId):
        tech = technician_id.value
        wh = SimpleNamespace()
        wh.is_closed = lambda: tech in self.closed_ids

        def _session_delta():
            if self.inventory_by_tech is None:
                return SimpleNamespace(
                    current_inventory_id="inv-1",
                    current_inventory_moment=_ANCHOR_DT,
                )
            counted_at = self.inventory_by_tech.get(tech)
            if counted_at is None:
                return None
            return SimpleNamespace(
                current_inventory_id=f"inv-{tech}",
                current_inventory_moment=counted_at,
            )

        wh.compute_warehouse_delta_between_latest_inventories = _session_delta
        return wh


@dataclass
class _EventStore:
    ids: tuple[str, ...] = ()

    def list_technician_ids(self) -> tuple[str, ...]:
        return self.ids


def test_import_transfers_cli_runs_without_cutover_env(capsys) -> None:
    importer = _FakeImporter()
    code = main(
        ["import-transfers", "--technician-id", "10001"],
        deps=_deps(importer=importer, warehouse_repository=_OpenRepo()),
    )
    assert code == 0
    assert importer.calls == [("10001", _ANCHOR_DT)]
    out = capsys.readouterr().out
    assert "imported=1" in out


def test_import_transfers_cli_requires_xor_scope() -> None:
    with pytest.raises(SystemExit):
        main(["import-transfers"])
    with pytest.raises(SystemExit):
        main(
            [
                "import-transfers",
                "--technician-id",
                "10001",
                "--all",
            ],
        )


def test_import_transfers_cli_uses_inventory_cutoff() -> None:
    """happy: importer.execute anchor_at = counted_at склада; argv без --anchor-at."""
    importer = _FakeImporter()
    cutoff = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    code = main(
        ["import-transfers", "--technician-id", "10001"],
        deps=_deps(
            importer=importer,
            warehouse_repository=_OpenRepo(inventory_by_tech={"10001": cutoff}),
        ),
    )
    assert code == 0
    assert importer.calls == [("10001", cutoff)]


def test_import_transfers_cli_all_uses_per_tech_inventory_cutoff() -> None:
    """edge: --all — у каждого техника свой counted_at как cutoff."""
    importer = _FakeImporter()
    cutoff_a = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    cutoff_b = datetime(2026, 7, 10, 8, 30, tzinfo=UTC)
    code = main(
        ["import-transfers", "--all"],
        deps=_deps(
            importer=importer,
            warehouse_repository=_OpenRepo(
                inventory_by_tech={"10001": cutoff_a, "10002": cutoff_b},
            ),
            event_store=_EventStore(ids=("10001", "10002")),
        ),
    )
    assert code == 0
    assert importer.calls == [("10001", cutoff_a), ("10002", cutoff_b)]


def test_import_transfers_cli_single_no_inventory_exits_nonzero(capsys) -> None:
    """error: single без inventory → exit ≠ 0 + текст blocker."""
    code = main(
        ["import-transfers", "--technician-id", "10001"],
        deps=_deps(
            importer=_FakeImporter(),
            warehouse_repository=_OpenRepo(inventory_by_tech={}),
        ),
    )
    assert code != 0
    assert "no technician warehouse inventory in window" in capsys.readouterr().out


def test_import_transfers_cli_all_skipped_no_inventory(capsys) -> None:
    """edge: --all без inv → status=skipped_no_inventory; не в failed; exit 0."""
    code = main(
        ["import-transfers", "--all"],
        deps=_deps(
            importer=_FakeImporter(),
            warehouse_repository=_OpenRepo(inventory_by_tech={}),
            event_store=_EventStore(ids=("10001", "10002")),
        ),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "status=skipped_no_inventory" in out
    assert "skipped_no_inventory=2" in out
    assert "failed=0" in out


def test_import_transfers_cli_stdout_counters_and_sample_cap(capsys) -> None:
    importer = _FakeImporter()
    code = main(
        ["import-transfers", "--technician-id", "10001"],
        deps=_deps(importer=importer, warehouse_repository=_OpenRepo()),
    )
    assert code == 0
    out = capsys.readouterr().out
    for key in (
        "imported=",
        "updated=",
        "voided=",
        "ignored=",
        "skipped_unresolved=",
        "truncated_non_domain=",
    ):
        assert key in out
    samples = [line for line in out.splitlines() if line.startswith("sample_document_id=")]
    assert len(samples) == 20


def test_import_transfers_cli_all_continues_and_fails_summary(capsys) -> None:
    importer = _FakeImporter(
        errors={"10002": RuntimeError("ms down")},
    )
    code = main(
        ["import-transfers", "--all"],
        deps=_deps(
            importer=importer,
            warehouse_repository=_OpenRepo(),
            event_store=_EventStore(ids=("10001", "10002", "10003")),
        ),
    )
    assert code != 0
    out = capsys.readouterr().out
    assert "technician_id=10001" in out
    assert "technician_id=10002" in out
    assert "error=" in out
    assert "technician_id=10003" in out
    assert "failed=1" in out
    assert len(importer.calls) == 3


def test_import_transfers_cli_single_exception_prints_error(capsys) -> None:
    importer = _FakeImporter(errors={"10001": RuntimeError("ms down")})
    code = main(
        ["import-transfers", "--technician-id", "10001"],
        deps=_deps(importer=importer, warehouse_repository=_OpenRepo()),
    )
    assert code != 0
    out = capsys.readouterr().out
    assert "error=ms down" in out
    assert "failed=" not in out
    assert len(importer.calls) == 1


def test_import_transfers_cli_closed_single_and_all_skipped(capsys) -> None:
    importer = _FakeImporter()
    code = main(
        ["import-transfers", "--technician-id", "10001"],
        deps=_deps(
            importer=importer,
            warehouse_repository=_OpenRepo(closed_ids=frozenset({"10001"})),
        ),
    )
    assert code != 0
    out = capsys.readouterr().out
    assert "warehouse is closed" in out
    assert "exit-reconcile" in out
    assert importer.calls == []

    importer2 = _FakeImporter()
    code = main(
        ["import-transfers", "--all"],
        deps=_deps(
            importer=importer2,
            warehouse_repository=_OpenRepo(closed_ids=frozenset({"10002"})),
            event_store=_EventStore(ids=("10001", "10002")),
        ),
    )
    assert code == 0  # skipped_closed не увеличивает failed
    out = capsys.readouterr().out
    assert "status=skipped_closed" in out
    assert "skipped_closed=1" in out
    assert "failed=0" in out
    assert len(importer2.calls) == 1
    assert importer2.calls[0][0] == "10001"
