from __future__ import annotations

from .fakes import read_repo


def test_new_plan_template_contains_bounded_contract_blocks() -> None:
    text = read_repo(".cursor/skills/planner/references/plan-templates.md")
    for marker in (
        "<!-- agent-progress:start -->",
        "<!-- agent-progress:end -->",
        "<!-- agent-contract-evidence:start -->",
        "<!-- agent-contract-evidence:end -->",
        "<!-- plan-code-review:start -->",
        "<!-- plan-code-review:end -->",
    ):
        assert marker in text


def test_author_contract_hashes_target_before_repository_write() -> None:
    author = read_repo(".cursor/skills/planner/SKILL.md")
    assert "сформировать target Markdown in-memory" in author
    assert "semantic_sha256" in author
    assert "activate --contract" in author
    assert author.index("semantic_sha256") < author.index("записать target")


def test_quality_fixes_require_new_plan_author_contract() -> None:
    quality = read_repo(".cursor/skills/planner/SKILL.md")
    assert "новый `plan-author` contract" in quality
    assert "verify" in quality
    assert "deactivate" in quality


def test_executor_requires_active_contract_and_cannot_expand_it() -> None:
    execute = read_repo(".cursor/skills/executor/SKILL.md")
    assert "contract_id" in execute
    assert "status" in execute
    assert "не создавать, не расширять и не деактивировать contract" in execute
    assert "agent-contract-evidence" in execute
    assert "verification-before-completion" in execute
    assert "не обновлять таблицу фрагментов pack README" in execute


def test_plan_templates_do_not_instruct_reviewer_to_write_plan() -> None:
    text = read_repo(".cursor/skills/planner/references/plan-templates.md")
    assert "всегда создаёт NA" not in text
    assert "loop пишет отчёт" not in text
    assert "ReviewMaterialization" in text or "materializ" in text.lower()


def test_process_contract_keeps_reviewer_read_only() -> None:
    review = read_repo(".cursor/skills/reviewer/SKILL.md")
    assert "не редактировать plan, `src/`, `tests/` или другие workspace files" in review
    assert "## ReviewMaterialization" in review
    assert "write_allowlist: []" in review
    assert "не reviewer" in review


def test_reviewer_secondary_docs_stay_read_only() -> None:
    skill = read_repo(".cursor/skills/reviewer/SKILL.md")
    checklist = read_repo(".cursor/skills/reviewer/references/review-checklist.md")
    assert "если пользователь попросил править план" not in skill
    assert "Обновить `**Статус post-review:**`" not in checklist
    assert "ReviewMaterialization" in checklist


def test_router_does_not_keep_retired_pipeline() -> None:
    orchestrator = read_repo(".cursor/skills/skill-orchestrator/SKILL.md")
    planner = read_repo(".cursor/skills/planner/SKILL.md")
    assert "autonomous-job" in orchestrator
    assert "post-author" not in orchestrator
    assert "pack-semi-auto" not in orchestrator
    assert "slice-index" not in orchestrator
    for command in ("activate", "verify", "deactivate"):
        assert command in planner


def test_spec_author_allowlist_excludes_runtime_code() -> None:
    orchestrator = read_repo(".cursor/skills/skill-orchestrator/SKILL.md")
    assert "spec-author" in orchestrator
    assert "не runtime-код" in orchestrator
    assert "accepted ADR" in orchestrator


def test_retired_pack_contract_is_not_an_execution_path() -> None:
    contract = read_repo(".cursor/skills/skill-orchestrator/references/pack-semi-auto-contract.md")
    execute = read_repo(".cursor/skills/executor/SKILL.md")
    assert "Не исполнять" in contract
    assert "post-author" not in contract
    assert "execute сейчас" not in contract
    assert "contract_id" in execute


def test_orchestrator_docs_scope_active_per_conversation() -> None:
    policy = read_repo(".cursor/agent-contract/README.md")
    text = read_repo(".cursor/skills/skill-orchestrator/SKILL.md")
    assert "conversation_id" in policy
    assert "bound_conversation_ids" in policy
    assert "Existing active contract блокирует" not in text
    lower = text.lower()
    assert "workspace mutex" not in lower or "снят" in lower
