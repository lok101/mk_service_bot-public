from __future__ import annotations

import json
from pathlib import Path

from scripts.lint_invariants import main


def _entry(
    invariant_id: str = "INV-REC-001",
    *,
    owner: str = "settlement",
    status: str = "active",
    evidence: tuple[tuple[str, str], ...] = (
        ("property-test", "tests/property/test_evidence.py::test_evidence"),
    ),
    superseded_by: str | None = None,
) -> str:
    lines = [
        "[[invariants]]",
        f"id = {json.dumps(invariant_id)}",
        'statement = "A registered invariant."',
        'scope = ["src/domain/inventory_reconciliation/"]',
        f"owner = {json.dumps(owner)}",
        f"status = {json.dumps(status)}",
    ]
    if superseded_by is not None:
        lines.append(f"superseded_by = {json.dumps(superseded_by)}")
    for method, target in evidence:
        lines.extend(
            (
                "",
                "[[invariants.evidence]]",
                f"method = {json.dumps(method)}",
                f"target = {json.dumps(target)}",
            ),
        )
    return "\n".join(lines)


def _write_repository(root: Path, *entries: str) -> None:
    registry = root / "verification" / "invariants.toml"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "schema_version = 1\n\n" + "\n\n".join(entries) + "\n",
        encoding="utf-8",
    )

    test_path = root / "tests" / "property" / "test_evidence.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_evidence() -> None:\n    pass\n", encoding="utf-8")

    tla_dir = root / "verification" / "tla"
    tla_dir.mkdir()
    (tla_dir / "Model.cfg").write_text(
        "SPECIFICATION Spec\nINVARIANT ClaimFencing\n",
        encoding="utf-8",
    )
    (tla_dir / "Model.tla").write_text(
        "---- MODULE Model ----\nClaimFencing == TRUE\n====\n",
        encoding="utf-8",
    )

    script_path = root / "scripts" / "check_dummy.py"
    script_path.parent.mkdir()
    script_path.write_text("from __future__ import annotations\n", encoding="utf-8")


def _run(root: Path, capsys: object) -> tuple[int, str]:
    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    return exit_code, captured.out  # type: ignore[no-any-return]


def test_valid_registry_with_pytest_and_self_check_evidence_passes(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(
        tmp_path,
        _entry(
            evidence=(
                ("property-test", "tests/property/test_evidence.py::test_evidence"),
                ("model-check", "verification/tla/Model.cfg#ClaimFencing"),
                ("self-check", "uv run python scripts/check_dummy.py"),
            ),
        ),
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 0
    assert output == "Invariant registry: OK (1)\n"


def test_duplicate_invariant_id_reports_inv002(tmp_path: Path, capsys: object) -> None:
    _write_repository(tmp_path, _entry(status="proposed", evidence=()), _entry())

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV002 duplicate invariant ID INV-REC-001" in output


def test_active_without_evidence_reports_inv006(tmp_path: Path, capsys: object) -> None:
    _write_repository(tmp_path, _entry(evidence=()))

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV006 active invariant INV-REC-001 requires executable evidence" in output


def test_broken_pytest_node_reports_inv010(tmp_path: Path, capsys: object) -> None:
    _write_repository(
        tmp_path,
        _entry(
            evidence=(("property-test", "tests/property/test_evidence.py::test_missing"),),
        ),
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV010 pytest node does not exist" in output
    assert "test_missing" in output


def test_markdown_only_target_reports_inv011(tmp_path: Path, capsys: object) -> None:
    _write_repository(
        tmp_path,
        _entry(evidence=(("property-test", "docs/invariant.md::test_evidence"),)),
    )
    docs_path = tmp_path / "docs" / "invariant.md"
    docs_path.parent.mkdir()
    docs_path.write_text("# Not executable\n", encoding="utf-8")

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV011 evidence target must not be Markdown" in output


def test_unknown_owner_method_and_status_report_stable_codes(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(
        tmp_path,
        _entry(
            owner="unknown",
            status="unknown",
            evidence=(("unknown", "tests/property/test_evidence.py::test_evidence"),),
        ),
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV004 unknown owner 'unknown'" in output
    assert "INV005 unknown status 'unknown'" in output
    assert "INV007 unknown evidence method 'unknown'" in output


def test_unregistered_inv_reference_in_test_reports_inv013(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(tmp_path, _entry(status="proposed", evidence=()))
    unregistered_id = "INV" + "-NEW-999"
    (tmp_path / "tests" / "property" / "test_evidence.py").write_text(
        f'"""Evidence for {unregistered_id}."""\ndef test_evidence() -> None:\n    pass\n',
        encoding="utf-8",
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert f"INV013 unregistered invariant reference {unregistered_id}" in output


def test_retired_id_requires_superseded_by_when_replaced(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(
        tmp_path,
        _entry(status="retired", evidence=()),
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV014 retired invariant INV-REC-001 requires superseded_by" in output


def test_retired_id_cannot_be_reused_as_new_active(tmp_path: Path, capsys: object) -> None:
    _write_repository(
        tmp_path,
        _entry(status="retired", evidence=(), superseded_by="INV-REC-002"),
        _entry(),
        _entry("INV-REC-002", status="proposed", evidence=()),
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV015 retired invariant ID INV-REC-001 cannot be reused" in output


def test_model_check_liveness_cfg_resolves_module_by_liveness_suffix(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(
        tmp_path,
        _entry(
            evidence=(
                (
                    "model-check",
                    "verification/tla/OutboxProtocolLiveness.cfg#EventuallyTerminal",
                ),
            ),
        ),
    )
    tla_dir = tmp_path / "verification" / "tla"
    (tla_dir / "OutboxProtocol.tla").write_text(
        "---- MODULE OutboxProtocol ----\nEventuallyTerminal == TRUE\n====\n",
        encoding="utf-8",
    )
    (tla_dir / "OutboxProtocolLiveness.cfg").write_text(
        "SPECIFICATION LivenessSpec\nPROPERTY EventuallyTerminal\n",
        encoding="utf-8",
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 0
    assert output == "Invariant registry: OK (1)\n"


def test_model_check_safety_cfg_without_property_reports_inv009(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(
        tmp_path,
        _entry(
            evidence=(("model-check", "verification/tla/OutboxProtocol.cfg#EventuallyTerminal"),),
        ),
    )
    tla_dir = tmp_path / "verification" / "tla"
    (tla_dir / "OutboxProtocol.tla").write_text(
        "---- MODULE OutboxProtocol ----\nEventuallyTerminal == TRUE\n====\n",
        encoding="utf-8",
    )
    (tla_dir / "OutboxProtocol.cfg").write_text(
        "SPECIFICATION Spec\nINVARIANT UniqueEventHandler\n",
        encoding="utf-8",
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV009" in output
    assert "EventuallyTerminal" in output


def test_model_check_cfg_without_module_or_known_suffix_reports_inv009(
    tmp_path: Path,
    capsys: object,
) -> None:
    _write_repository(
        tmp_path,
        _entry(evidence=(("model-check", "verification/tla/Orphan.cfg#ClaimFencing"),)),
    )
    (tmp_path / "verification" / "tla" / "Orphan.cfg").write_text(
        "SPECIFICATION Spec\nINVARIANT ClaimFencing\n",
        encoding="utf-8",
    )

    exit_code, output = _run(tmp_path, capsys)

    assert exit_code == 1
    assert "INV009" in output
    assert "model-check module does not exist" in output
