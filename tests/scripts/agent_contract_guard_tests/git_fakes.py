from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.agent_contract_guard_lib.git_snapshot import ActivationSnapshot
from scripts.agent_contract_guard_lib.lifecycle import (
    ActiveContract,
    activate_contract,
    record_verification,
)
from scripts.agent_contract_guard_lib.models import AgentContract, ContractRole, HashedPath
from scripts.agent_contract_guard_lib.schema import load_contract
from scripts.agent_contract_guard_lib.verification import VerificationResult, verify_contract
from tests.scripts.agent_contract_guard_tests.fakes import (
    APPROVED_SPEC,
    PLAN_PATH,
    contract_payload,
    plan_text,
    sha256_text,
    write_text,
)

write = write_text


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )


def hashed_path(relative: str, content: str) -> HashedPath:
    return HashedPath(path=relative, sha256=sha256_text(content))


def init_git_repo(root: Path) -> str:
    run_git(root, "init")
    run_git(root, "config", "user.email", "agent-contract@example.invalid")
    run_git(root, "config", "user.name", "Agent Contract Tests")
    write_text(root, "docs/specs/design.md", "approved\n")
    write_text(root, PLAN_PATH, plan_text())
    run_git(root, "add", ".")
    run_git(root, "commit", "-m", "baseline")
    return run_git(root, "rev-parse", "HEAD").stdout.strip()


def write_external_contract(
    outside: Path,
    *,
    baseline_ref: str,
    conversation_id: str = "conv-test",
    allowlist: tuple[str, ...] = ("src/allowed.py",),
    contract_id: str = "aec-11111111-1111-1111-1111-111111111111",
    preexisting: tuple[HashedPath | dict[str, str], ...] = (),
) -> Path:
    payload = contract_payload(
        baseline_ref=baseline_ref,
        conversation_id=conversation_id,
        allowlist=allowlist,
        preexisting=preexisting,
    )
    payload["contract_id"] = contract_id
    if outside.suffix == ".json":
        path = outside
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        outside.mkdir(parents=True, exist_ok=True)
        path = outside / "input-contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def activate_fixture(
    root: Path,
    *,
    role: ContractRole,
    baseline_ref: str,
    allowlist: tuple[str, ...] = (),
    protected: tuple[str, ...] = (),
    preexisting: tuple[str, ...] = (),
) -> tuple[AgentContract, ActivationSnapshot]:
    hashed = tuple(
        hashed_path(path, (root / path).read_text(encoding="utf-8")) for path in preexisting
    )
    payload = contract_payload(
        role=role,
        baseline_ref=baseline_ref,
        allowlist=allowlist,
        protected=protected,
        preexisting=hashed,
    )
    input_path = root.parent / f"input-contract-{root.name}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    active = activate_contract(root, input_path)
    return (
        load_contract(root / active.canonical_path, workspace=root),
        active.activation_snapshot,
    )


def activate_valid_fixture(
    root: Path,
    *,
    role: ContractRole = ContractRole.EXECUTOR,
    conversation_id: str = "conv-test",
    baseline_ref: str | None = None,
    allowlist: tuple[str, ...] = ("src/allowed.py",),
    protected: tuple[str, ...] | None = None,
    bound_conversation_ids: tuple[str, ...] = (),
    preexisting: tuple[str, ...] = (),
) -> ActiveContract:
    ref = baseline_ref or init_git_repo(root)
    hashed = tuple(
        hashed_path(path, (root / path).read_text(encoding="utf-8")) for path in preexisting
    )
    payload_kwargs: dict[str, object] = {
        "role": role,
        "baseline_ref": ref,
        "conversation_id": conversation_id,
        "allowlist": allowlist,
        "preexisting": hashed,
        "bound_conversation_ids": bound_conversation_ids,
    }
    if protected is not None:
        payload_kwargs["protected"] = protected
    payload = contract_payload(**payload_kwargs)  # type: ignore[arg-type]
    input_path = root.parent / f"input-contract-{root.name}-{conversation_id}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    return activate_contract(root, input_path)


def write_external_contract_and_activate(
    root: Path,
    *,
    conversation_id: str,
    allowlist: tuple[str, ...],
    contract_id: str,
    baseline_ref: str,
    role: ContractRole = ContractRole.EXECUTOR,
    protected: tuple[str, ...] | None = None,
    bound_conversation_ids: tuple[str, ...] = (),
) -> ActiveContract:
    outside = root.parent / f"external-contract-{root.name}-{conversation_id}.json"
    write_external_contract(
        outside,
        baseline_ref=baseline_ref,
        conversation_id=conversation_id,
        allowlist=allowlist,
        contract_id=contract_id,
    )
    payload = json.loads(outside.read_text(encoding="utf-8"))
    if protected is not None:
        payload["protected_paths"] = list(protected)
    if bound_conversation_ids:
        payload["bound_conversation_ids"] = list(bound_conversation_ids)
    outside.write_text(json.dumps(payload), encoding="utf-8")
    return activate_contract(root, outside)


def activate_two_conversations(workspace: Path, a: str, b: str) -> None:
    baseline = init_git_repo(workspace)
    activate_valid_fixture(
        workspace, conversation_id=a, allowlist=("src/a.py",), baseline_ref=baseline
    )
    write_external_contract_and_activate(
        workspace,
        conversation_id=b,
        allowlist=("docs/plans/b.md",),
        contract_id="aec-22222222-2222-2222-2222-222222222222",
        baseline_ref=baseline,
    )


def activate_executor_and_plan_author(workspace: Path) -> None:
    activate_two_conversations(workspace, "conv-a", "conv-b")


def activate_executor_with_approved_spec(workspace: Path, *, conversation_id: str) -> None:
    baseline = init_git_repo(workspace)
    activate_valid_fixture(
        workspace,
        conversation_id=conversation_id,
        role=ContractRole.EXECUTOR,
        allowlist=("src/allowed.py",),
        protected=(APPROVED_SPEC,),
        baseline_ref=baseline,
    )


def deactivate_all(workspace: Path) -> None:
    pointer = workspace / ".cursor/agent-contract/runtime/active.json"
    if pointer.is_file():
        pointer.unlink()


def activate_executor(
    root: Path, *, allowlist: tuple[str, ...] = ("src/allowed.py",)
) -> ActiveContract:
    baseline = init_git_repo(root)
    payload = contract_payload(
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=allowlist,
    )
    input_path = root.parent / f"input-executor-{root.name}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    return activate_contract(root, input_path)


def passing_result() -> VerificationResult:
    return VerificationResult(
        contract_id="aec-11111111-1111-1111-1111-111111111111",
        role=ContractRole.EXECUTOR,
        changed_paths=(),
        violations=(),
    )


def passing_result_for(root: Path) -> VerificationResult:
    pointer = json.loads(
        (root / ".cursor/agent-contract/runtime/active.json").read_text(encoding="utf-8")
    )
    by_conversation = pointer["by_conversation"]
    _conversation_id, entry = next(iter(by_conversation.items()))
    contract = load_contract(root / entry["canonical_path"], workspace=root)
    return verify_contract(
        root, contract, ActivationSnapshot(hashes_by_path=entry["activation_snapshot"])
    )


def active_contract_exists(root: Path) -> bool:
    return (root / ".cursor/agent-contract/runtime/active.json").is_file()


def mark_stale(root: Path, active: ActiveContract) -> None:
    pointer = root / ".cursor/agent-contract/runtime/active.json"
    data = json.loads(pointer.read_text(encoding="utf-8"))
    entry = data["by_conversation"][active.conversation_id]
    entry["stale"] = True
    entry["owner_generation"] = "dead-parent"
    pointer.write_text(json.dumps(data), encoding="utf-8")


def toggle_progress(plan: Path) -> None:
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("- [ ]", "- [x]", 1),
        encoding="utf-8",
    )


def prepare_cli_fixture(root: Path, argv: list[str]) -> ActiveContract:
    active = activate_valid_fixture(root)
    if argv and argv[0] == "verify":
        record_verification(
            root,
            verify_contract(
                root,
                load_contract(root / active.canonical_path, workspace=root),
                active.activation_snapshot,
            ),
        )
    return active


def prepare_violating_active_contract(root: Path) -> ActiveContract:
    from scripts.agent_contract_guard_lib.attribution import record_attributed_write

    active = activate_valid_fixture(root)
    write(root, "src/not-allowed.py", "bad\n")
    record_attributed_write(root, conversation_id=active.conversation_id, path="src/not-allowed.py")
    return active


def commit_all(root: Path, message: str) -> str:
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", message)
    return run_git(root, "rev-parse", "HEAD").stdout.strip()


def tree_has_path(root: Path, ref: str, relative: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{relative}"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    return result.returncode == 0


def install_guard_tree_without_hooks(root: Path, *, overwrite: bool = False) -> None:
    write_text(
        root,
        ".cursor/agent-contract/schema.json",
        '{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
    )
    write_text(root, "scripts/agent_contract_guard.py", "print('guard')\n")
    write_text(root, "scripts/agent_contract_guard_lib/__init__.py", "")
    write_text(root, ".github/CODEOWNERS", "/.cursor/agent-contract/ @lok101\n")
    if overwrite:
        write_text(root, "scripts/agent_contract_guard.py", "print('replaced')\n")


def init_git_repo_with_guard_without_hooks(root: Path) -> str:
    init_git_repo(root)
    install_guard_tree_without_hooks(root)
    return commit_all(root, "install guard without hooks")


def write_canonical_contract(
    root: Path,
    *,
    role: ContractRole,
    baseline_ref: str,
    allowlist: tuple[str, ...],
) -> Path:
    payload = contract_payload(role=role, baseline_ref=baseline_ref, allowlist=allowlist)
    path = root / ".cursor/agent-contract/contracts" / (str(payload["contract_id"]) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_executor_contract_for_plan(root: Path, baseline_ref: str) -> Path:
    return write_canonical_contract(
        root,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline_ref,
        allowlist=(PLAN_PATH,),
    )


def amended_plan(*, title: str) -> str:
    return plan_text().replace("## Задача 1", f"## Задача 1\n## Задача 4A: {title}")


def write_plan_author_amendment_contract(root: Path, baseline_ref: str, *, title: str) -> Path:
    from scripts.agent_contract_guard_lib.projection import semantic_plan_sha256

    contract_id = "aec-22222222-2222-2222-2222-222222222222"
    payload = contract_payload(
        role=ContractRole.PLAN_AUTHOR,
        baseline_ref=baseline_ref,
        allowlist=(PLAN_PATH,),
    )
    payload["contract_id"] = contract_id
    payload["created_at"] = "2026-09-14T12:01:00Z"
    payload["plan"] = {
        "path": PLAN_PATH,
        "semantic_sha256": semantic_plan_sha256(
            amended_plan(title=title), role=ContractRole.PLAN_AUTHOR
        ),
    }
    path = root / ".cursor/agent-contract/contracts" / f"{contract_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
