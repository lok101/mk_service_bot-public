from __future__ import annotations

from scripts.agent_process_report_lib.evidence import build_hard_deny_evidence
from scripts.agent_process_report_lib.models import (
    REDACTION_VERSION,
    ReportKind,
    ReportOutcome,
    new_report,
)


def test_hard_deny_evidence_has_fingerprint_and_path_hints() -> None:
    evidence = build_hard_deny_evidence(
        command="Remove-Item -Recurse C:\\repo\\tasks\\foo",
        path_hints=("tasks/foo",),
    )
    assert evidence["command_family"] == "shell"
    assert "command_fingerprint" in evidence
    assert "Remove-Item" in evidence["command_fingerprint"]
    assert evidence["path_hints"] == ["tasks/foo"]
    assert "tool_input" not in evidence


def test_tool_deny_evidence_includes_tool_name() -> None:
    evidence = build_hard_deny_evidence(
        tool_name="SomeOtherTool",
        path_hints=("src/allowed.py",),
    )
    assert evidence["command_family"] == "tool"
    assert evidence["tool_name"] == "SomeOtherTool"
    assert evidence["path_hints"] == ["src/allowed.py"]


def test_empty_fingerprint_still_records_family() -> None:
    evidence = build_hard_deny_evidence(command="")
    assert evidence["command_family"] == "shell"
    assert "command_fingerprint" not in evidence


def test_redaction_drops_sensitive_unknown_fields() -> None:
    evidence = build_hard_deny_evidence(
        command="echo token=super-secret-value-here",
        extra={
            "tool_input": {"path": "src/x.py", "contents": "secret"},
            "stdout": "full dump",
            "stderr": "err dump",
            "exit_code": 1,
        },
    )
    assert "tool_input" not in evidence
    assert "stdout" not in evidence
    assert "stderr" not in evidence
    assert evidence["exit_code"] == 1
    assert "super-secret-value-here" not in evidence["command_fingerprint"]
    assert "[REDACTED]" in evidence["command_fingerprint"]


def test_redaction_version_bumped() -> None:
    assert REDACTION_VERSION >= 2
    report = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="aec.hook",
        operation="tool:Write",
        signature="agt003",
        expected="allow",
        actual="deny",
        evidence={"command_family": "tool"},
    )
    assert report.redaction_version == REDACTION_VERSION
