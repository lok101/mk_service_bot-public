from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.cli import main
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    activate_executor,
    prepare_cli_fixture,
    prepare_violating_active_contract,
)


@pytest.mark.parametrize(
    ("argv", "expected_phase"),
    [
        (["status"], "status"),
        (["verify", "--base", "HEAD"], "verify"),
    ],
)
def test_cli_emits_one_json_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_phase: str,
) -> None:
    prepare_cli_fixture(tmp_path, argv)
    exit_code = main([*argv, "--root", str(tmp_path)])
    record = json.loads(capsys.readouterr().out.strip())
    assert record["phase"] == expected_phase
    assert exit_code in {0, 1}


def test_cli_verify_returns_one_for_sorted_violations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_violating_active_contract(tmp_path)
    assert main(["verify", "--root", str(tmp_path)]) == 1
    record = json.loads(capsys.readouterr().out)
    assert [item["code"] for item in record["violations"]] == sorted(
        item["code"] for item in record["violations"]
    )
    assert "tool_input" not in record


def test_cli_preflight_denies_path_outside_allowlist(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_cli_fixture(tmp_path, ["preflight"])
    input_path = tmp_path / "tool.json"
    input_path.write_text(
        json.dumps({"path": "src/forbidden.py", "contents": "nope"}),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "preflight",
                "--tool",
                "Write",
                "--input-json",
                str(input_path),
                "--root",
                str(tmp_path),
            ]
        )
        == 1
    )
    record = json.loads(capsys.readouterr().out)
    assert record["phase"] == "preflight"
    assert record["violations"][0]["code"] == "AGT003"


def test_hook_cli_denies_write_with_exit_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "conversation_id": "conv-test",
                    "tool_name": "Write",
                    "tool_input": {"path": "src/forbidden.py", "contents": "x"},
                }
            )
        ),
    )
    assert main(["hook", "--event", "preToolUse", "--root", str(tmp_path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["permission"] == "deny"
    assert "AGT003" in payload["agent_message"]


def test_status_lists_all_conversation_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.agent_contract_guard_lib.lifecycle import activate_contract
    from tests.scripts.agent_contract_guard_tests.git_fakes import (
        init_git_repo,
        write_external_contract,
    )

    baseline = init_git_repo(tmp_path)
    a = write_external_contract(
        tmp_path.parent / "a.json",
        baseline_ref=baseline,
        conversation_id="conv-a",
    )
    b = write_external_contract(
        tmp_path.parent / "b.json",
        baseline_ref=baseline,
        conversation_id="conv-b",
        contract_id="aec-22222222-2222-2222-2222-222222222222",
    )
    activate_contract(tmp_path, a)
    activate_contract(tmp_path, b)
    result_code = main(["status", "--root", str(tmp_path)])
    assert result_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    keys = {item["conversation_id"] for item in payload["by_conversation"]}
    assert keys == {"conv-a", "conv-b"}


def test_hook_cli_accepts_utf8_bom_prefixed_pretool_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    body = json.dumps(
        {
            "conversation_id": "conv-test",
            "tool_name": "Write",
            "tool_input": {"path": "src/allowed.py", "contents": "ok"},
            "cwd": str(tmp_path),
            "workspace_roots": [str(tmp_path)],
        }
    ).encode("utf-8")
    bom_stdin = io.BytesIO(b"\xef\xbb\xbf" + body)

    class _BomStdin:
        buffer = bom_stdin

        def read(self) -> str:
            raise AssertionError("hook CLI must read sys.stdin.buffer, not text read()")

    monkeypatch.setattr(sys, "stdin", _BomStdin())
    assert main(["hook", "--event", "preToolUse", "--root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"permission": "allow"}
    assert "invalid hook JSON" not in json.dumps(payload)
