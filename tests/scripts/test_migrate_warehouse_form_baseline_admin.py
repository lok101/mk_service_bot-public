from __future__ import annotations

import pytest
from scripts.migrate_warehouse_form_baseline_admin import (
    apply_updates,
    build_parser,
    plan_updates,
)


def _form_event(*, tech: str = "10017", baseline: bool = True) -> dict:
    return {
        "aggregate_id": tech,
        "event_type": "TechnicianWarehouseInventoryCounted",
        "payload": {
            "inventory_id": "inv-1",
            "form_token": "eyJ.jwt",
            "baseline": baseline,
        },
    }


def _seed_event(*, tech: str = "10017") -> dict:
    return {
        "aggregate_id": tech,
        "event_type": "TechnicianWarehouseInventoryCounted",
        "payload": {
            "inventory_id": "seed:10017:t",
            "form_token": "seed:10017:t",
            "baseline": True,
        },
    }


def test_migrate_dry_run_lists_form_baseline_events() -> None:
    # happy
    docs = [_form_event(), _seed_event(), _form_event(tech="10018")]
    matched = plan_updates(docs, technician_id=None)  # --all
    assert len(matched) == 2
    assert all(not d["payload"]["form_token"].startswith("seed:") for d in matched)


def test_migrate_confirm_sets_baseline_false() -> None:
    # happy
    docs = [_form_event()]
    matched = plan_updates(docs, technician_id="10017")
    updated = apply_updates(matched, confirm=True)
    assert updated == 1
    assert docs[0]["payload"]["baseline"] is False


def test_migrate_skips_seed_form_token() -> None:
    # edge
    docs = [_seed_event()]
    assert plan_updates(docs, technician_id="10017") == []


def test_migrate_confirm_is_idempotent() -> None:
    # idempotency
    docs = [_form_event()]
    apply_updates(plan_updates(docs, technician_id="10017"), confirm=True)
    assert plan_updates(docs, technician_id="10017") == []


def test_parser_requires_technician_id_xor_all() -> None:
    # error
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_accepts_technician_id() -> None:
    args = build_parser().parse_args(["--technician-id", "10017"])
    assert args.technician_id == "10017"
    assert args.all is False


def test_parser_accepts_all() -> None:
    args = build_parser().parse_args(["--all"])
    assert args.all is True
