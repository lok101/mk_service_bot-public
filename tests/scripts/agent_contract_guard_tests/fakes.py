from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_contract_guard_lib.models import ContractRole, HashedPath
from scripts.agent_contract_guard_lib.projection import semantic_plan_sha256

APPROVED_SPEC = "docs/specs/design.md"
PLAN_PATH = "docs/plans/plan.md"


def read_repo(relative: str) -> str:
    return Path(relative).read_text(encoding="utf-8")


def sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def plan_text() -> str:
    return """<!-- agent-progress:start -->
- [ ] Выполнить test
<!-- agent-progress:end -->
## Задача 1
<!-- agent-contract-evidence:start -->
_(пусто)_
<!-- agent-contract-evidence:end -->
<!-- plan-code-review:start -->
Статус: —
<!-- plan-code-review:end -->
"""


def _serialize_preexisting(
    preexisting: tuple[HashedPath | dict[str, str], ...],
) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    for item in preexisting:
        if isinstance(item, HashedPath):
            serialized.append({"path": item.path, "sha256": item.sha256})
        else:
            serialized.append(item)
    return serialized


def contract_payload(
    *,
    role: ContractRole = ContractRole.EXECUTOR,
    baseline_ref: str = "0" * 40,
    allowlist: tuple[str, ...] = ("src/allowed.py",),
    protected: tuple[str, ...] = (APPROVED_SPEC,),
    preexisting: tuple[HashedPath | dict[str, str], ...] = (),
    conversation_id: str = "conv-test",
    bound_conversation_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    spec_hash = sha256_text("approved\n")
    return {
        "schema_version": 1,
        "contract_id": "aec-11111111-1111-1111-1111-111111111111",
        "role": role.value,
        "stage_target": (APPROVED_SPEC if role is ContractRole.SPEC_AUTHOR else PLAN_PATH),
        "baseline_ref": baseline_ref,
        "approved_inputs": [{"path": APPROVED_SPEC, "sha256": spec_hash}],
        "write_allowlist": [] if role is ContractRole.REVIEWER else list(allowlist),
        "protected_paths": list(protected),
        "preexisting_paths": _serialize_preexisting(preexisting),
        "plan": {
            "path": PLAN_PATH,
            "semantic_sha256": semantic_plan_sha256(plan_text(), role=role),
        },
        "created_at": "2026-09-14T12:00:00Z",
        "created_by": "skill-orchestrator",
        "conversation_id": conversation_id,
        **(
            {"bound_conversation_ids": list(bound_conversation_ids)}
            if bound_conversation_ids
            else {}
        ),
    }


def write_contract(root: Path, payload: dict[str, object]) -> Path:
    write_text(root, APPROVED_SPEC, "approved\n")
    write_text(root, PLAN_PATH, plan_text())
    path = root / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
