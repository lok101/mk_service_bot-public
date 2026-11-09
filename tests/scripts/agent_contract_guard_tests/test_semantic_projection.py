from __future__ import annotations

import hashlib

import pytest
from scripts.agent_contract_guard_lib.models import ContractRole
from scripts.agent_contract_guard_lib.projection import SemanticPlanError, semantic_plan_sha256

from .fakes import plan_text


def test_semantic_projection_allows_progress_and_evidence_updates() -> None:
    before = plan_text()
    after = before.replace("- [ ] Выполнить test", "- [x] Выполнить test").replace(
        "_(пусто)_", "verify → exit 0"
    )
    assert semantic_plan_sha256(before, role=ContractRole.EXECUTOR) == semantic_plan_sha256(
        after, role=ContractRole.EXECUTOR
    )


def test_semantic_projection_rejects_task_drift_and_invalid_markers() -> None:
    before = plan_text()
    assert semantic_plan_sha256(before, role=ContractRole.EXECUTOR) != semantic_plan_sha256(
        before.replace("Выполнить test", "Изменить design spec"),
        role=ContractRole.EXECUTOR,
    )
    for invalid in (
        before.replace("<!-- agent-progress:end -->", ""),
        before.replace(
            "<!-- agent-progress:end -->",
            "<!-- agent-progress:start -->\n<!-- agent-progress:end -->",
        ),
        before.replace("agent-progress:start", "unknown:start"),
    ):
        with pytest.raises(SemanticPlanError, match="AGT004"):
            semantic_plan_sha256(invalid, role=ContractRole.EXECUTOR)


def test_executor_projection_keeps_review_block_immutable() -> None:
    before = plan_text()
    after = before.replace("Статус: —", "Статус: forged-clean")
    assert semantic_plan_sha256(before, role=ContractRole.EXECUTOR) != semantic_plan_sha256(
        after, role=ContractRole.EXECUTOR
    )


def test_plan_author_projection_accepts_precomputed_review_materialization() -> None:
    target = plan_text().replace("Статус: —", "Статус: findings-open")
    assert (
        semantic_plan_sha256(target, role=ContractRole.PLAN_AUTHOR)
        == hashlib.sha256(target.replace("\r\n", "\n").encode()).hexdigest()
    )
