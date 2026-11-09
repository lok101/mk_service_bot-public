from __future__ import annotations

import json
from pathlib import Path

from scripts.commit_allowlist_groups import (
    _assemble_groups,
    _Candidate,
    _gate_leftover,
    hygiene_deletes,
)
from tests.scripts.agent_contract_guard_tests.fakes import contract_payload, write_text


def _write_active(workspace: Path, *, canonical_path: str, contract_id: str) -> None:
    pointer = workspace / ".cursor/agent-contract/runtime/active.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "by_conversation": {
                    "conv-a": {
                        "contract_id": contract_id,
                        "canonical_path": canonical_path,
                        "activated_at": "2026-10-21T00:00:00+00:00",
                        "activation_snapshot": {},
                        "last_verify_digest": None,
                        "last_verify_passed": None,
                        "owner_generation": None,
                        "stale": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_hygiene_deletes_happy_orphan_invalid(tmp_path: Path) -> None:
    rel = ".cursor/agent-contract/contracts/aec-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.json"
    write_text(tmp_path, rel, "{not-json")
    deletes, skipped = hygiene_deletes(tmp_path, [rel])
    assert deletes == [rel]
    assert skipped == []


def test_hygiene_deletes_edge_active_invalid_skipped(tmp_path: Path) -> None:
    cid = "aec-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rel = f".cursor/agent-contract/contracts/{cid}.json"
    write_text(tmp_path, rel, "{broken")
    _write_active(tmp_path, canonical_path=rel, contract_id=cid)
    deletes, skipped = hygiene_deletes(tmp_path, [rel])
    assert deletes == []
    assert skipped == [rel]


def test_hygiene_deletes_error_valid_dirty_not_deleted(tmp_path: Path) -> None:
    payload = contract_payload()
    cid = str(payload["contract_id"])
    rel = f".cursor/agent-contract/contracts/{cid}.json"
    write_text(tmp_path, "docs/specs/design.md", "approved\n")
    write_text(
        tmp_path,
        "docs/plans/plan.md",
        """<!-- agent-progress:start -->
- [ ] Выполнить test
<!-- agent-progress:end -->
## Задача 1
<!-- agent-contract-evidence:start -->
_(пусто)_
<!-- agent-contract-evidence:end -->
<!-- plan-code-review:start -->
Статус: —
<!-- plan-code-review:end -->
""",
    )
    write_text(tmp_path, rel, json.dumps(payload))
    deletes, skipped = hygiene_deletes(tmp_path, [rel])
    assert deletes == []
    assert skipped == []


def _cand(
    *,
    contract_id: str,
    write_allowlist: tuple[str, ...] = (),
    approved_inputs: tuple[str, ...] = (),
    created_at: str = "2026-10-12T00:00:00+00:00",
) -> _Candidate:
    return _Candidate(
        contract_id=contract_id,
        role="executor",
        stage_target="docs/plans/x.md",
        canonical_path=f".cursor/agent-contract/contracts/{contract_id}.json",
        write_allowlist=write_allowlist,
        approved_inputs=approved_inputs,
        created_at=created_at,
        source="test",
    )


def test_assemble_groups_happy_approved_inputs_only() -> None:
    dirty = ["docs/specs/foo-design.md"]
    candidates = [
        _cand(
            contract_id="aec-ai",
            approved_inputs=("docs/specs/foo-design.md",),
        )
    ]
    payload = _assemble_groups(dirty, candidates)
    assert payload["group_count"] == 1
    assert payload["groups"][0]["paths"] == ["docs/specs/foo-design.md"]
    assert payload["groups"][0]["match_kind"] == "approved_inputs"
    assert payload["uncovered"] == []
    assert payload["gate_leftover"] == []
    assert payload["final_gate_blocked"] is False


def test_assemble_groups_edge_allowlist_wins_no_duplicate() -> None:
    dirty = ["docs/specs/foo-design.md", "scripts/x.py"]
    candidates = [
        _cand(
            contract_id="aec-both",
            write_allowlist=("docs/specs/foo-design.md", "scripts/x.py"),
            approved_inputs=("docs/specs/foo-design.md",),
        )
    ]
    payload = _assemble_groups(dirty, candidates)
    kinds = [g["match_kind"] for g in payload["groups"]]
    assert kinds == ["write_allowlist"]
    assert payload["groups"][0]["paths"] == [
        "docs/specs/foo-design.md",
        "scripts/x.py",
    ]
    assert payload["uncovered"] == []
    assert payload["gate_leftover"] == []


def test_assemble_groups_error_uncovered_outside_docs_blocks() -> None:
    dirty = ["docs/specs/other-design.md", "src/foo.py", "tests/x.py"]
    candidates = [_cand(contract_id="aec-empty")]
    payload = _assemble_groups(dirty, candidates)
    assert payload["uncovered"] == [
        "docs/specs/other-design.md",
        "src/foo.py",
        "tests/x.py",
    ]
    assert payload["gate_leftover"] == [
        "docs/specs/other-design.md",
        "src/foo.py",
        "tests/x.py",
    ]
    assert payload["final_gate_blocked"] is True


def test_gate_leftover_is_full_uncovered() -> None:
    remaining = {
        "docs/specs/a.md",
        "docs/adr/0036.md",
        "docs/ui-adr/x.md",
        "docs/plans/p.md",
        "tasks/t/TASK.md",
        "src/x.py",
        "README.md",
        "tests/y.py",
    }
    assert _gate_leftover(remaining) == sorted(remaining)
