from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from scripts.check_formal_models import (
    JAVA_INSTALL_HINT,
    ChecksumMismatchError,
    ModelRun,
    ensure_tlc_jar,
    load_tool,
    main,
    run_model,
    safety_invariants,
)

_PINNED_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
_PINNED_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
_JAVA17 = 'openjdk version "17.0.9" 2023-10-17\nOpenJDK Runtime Environment\n'


class _CommandStub:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.version_output = _JAVA17
        self.version_returncode = 0
        self.tlc_returncode = 0
        self.tlc_stdout = "Model checking completed. No error has been found.\n"
        self.tlc_stderr = ""
        self.raise_file_not_found = False

    def __call__(self, args: Sequence[str], **_kwargs: object) -> CompletedProcess[str]:
        command = [str(part) for part in args]
        self.commands.append(command)
        if self.raise_file_not_found:
            raise FileNotFoundError("java")
        if command[:2] == ["java", "-version"]:
            return CompletedProcess(
                args=command,
                returncode=self.version_returncode,
                stdout="",
                stderr=self.version_output,
            )
        return CompletedProcess(
            args=command,
            returncode=self.tlc_returncode,
            stdout=self.tlc_stdout,
            stderr=self.tlc_stderr,
        )

    def tlc_commands(self) -> list[list[str]]:
        return [command for command in self.commands if "tlc2.TLC" in command]


def _write_tool_tree(root: Path) -> Path:
    tla_dir = root / "verification" / "tla"
    tla_dir.mkdir(parents=True)
    (tla_dir / "tlc-tool.toml").write_text(
        (
            'version = "v1.7.4"\n'
            f'url = "{_PINNED_URL}"\n'
            f'sha256 = "{_PINNED_SHA256}"\n'
            "minimum_java_major = 11\n"
        ),
        encoding="utf-8",
    )
    (tla_dir / "OutboxProtocol.tla").write_text(
        "---- MODULE OutboxProtocol ----\nSpec == TRUE\n====\n",
        encoding="utf-8",
    )
    config = tla_dir / "OutboxProtocol.cfg"
    config.write_text("SPECIFICATION Spec\nINVARIANT UniqueEventHandler\n", encoding="utf-8")
    return config


def _seed_cached_jar(root: Path) -> Path:
    jar = root / ".cache" / "verification" / "tla2tools.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"pinned-tlc-jar")
    return jar


def test_runner_uses_cached_jar_only_after_sha256_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    downloads: list[tuple[str, Path]] = []

    def fake_download(url: str, destination: Path) -> None:
        downloads.append((url, destination))
        raise AssertionError("cached jar must not be downloaded")

    stub = _CommandStub()
    monkeypatch.setattr("scripts.check_formal_models._download_url", fake_download)
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)

    resolved = ensure_tlc_jar(root=tmp_path, tool=load_tool(tmp_path))
    exit_code = run_model(root=tmp_path, jar=resolved, run=ModelRun(config=config))

    assert resolved == jar
    assert downloads == []
    assert exit_code == 0
    assert stub.tlc_commands()


def test_runner_downloads_missing_jar_and_checks_sha256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_tool_tree(tmp_path)
    downloaded: list[tuple[str, Path]] = []

    def fake_download(url: str, destination: Path) -> None:
        downloaded.append((url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"downloaded-jar")

    monkeypatch.setattr("scripts.check_formal_models._download_url", fake_download)
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )

    resolved = ensure_tlc_jar(root=tmp_path, tool=load_tool(tmp_path))

    assert downloaded == [(_PINNED_URL, downloaded[0][1])]
    assert resolved == tmp_path / ".cache" / "verification" / "tla2tools.jar"
    assert resolved.read_bytes() == b"downloaded-jar"


def test_runner_rejects_checksum_mismatch_without_starting_java(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_tool_tree(tmp_path)
    _seed_cached_jar(tmp_path)
    stub = _CommandStub()
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: "0" * 64,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)

    with pytest.raises(ChecksumMismatchError, match="SHA-256"):
        ensure_tlc_jar(root=tmp_path, tool=load_tool(tmp_path))
    assert main(["--root", str(tmp_path), "--config", "verification/tla/OutboxProtocol.cfg"]) == 1
    assert stub.commands == []


def test_runner_rejects_java_below_11_with_install_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_tool_tree(tmp_path)
    _seed_cached_jar(tmp_path)
    stub = _CommandStub()
    stub.version_output = 'java version "1.8.0_392"\n'
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)

    exit_code = main(["--root", str(tmp_path), "--config", "verification/tla/OutboxProtocol.cfg"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out.strip() == JAVA_INSTALL_HINT
    assert stub.tlc_commands() == []


def test_runner_passes_fixed_workers_seed_and_config_to_tlc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    stub = _CommandStub()
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)

    exit_code = run_model(root=tmp_path, jar=jar, run=ModelRun(config=config))

    assert exit_code == 0
    assert stub.tlc_commands() == [
        [
            "java",
            "-XX:+UseParallelGC",
            "-cp",
            str(jar),
            "tlc2.TLC",
            "-workers",
            "1",
            "-seed",
            "20260914",
            "-config",
            str(config),
            "-metadir",
            str(tmp_path / ".cache" / "verification" / "tlc-states" / "OutboxProtocol"),
            "OutboxProtocol",
        ]
    ]


def test_runner_writes_stdout_trace_file_on_unexpected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    stub = _CommandStub()
    stub.tlc_returncode = 1
    stub.tlc_stdout = "Error: Invariant UniqueEventHandler is violated.\n"
    stub.tlc_stderr = "states generated\n"
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)

    exit_code = run_model(root=tmp_path, jar=jar, run=ModelRun(config=config))
    trace_path = tmp_path / ".cache" / "verification" / "traces" / "OutboxProtocol.trace"

    assert exit_code == 1
    assert trace_path.is_file()
    trace = trace_path.read_text(encoding="utf-8")
    assert "Invariant UniqueEventHandler is violated" in trace
    assert "states generated" in trace


def test_runner_raw_exit_returns_tlc_process_code_without_expected_interpretation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    stub = _CommandStub()
    stub.tlc_returncode = 12
    stub.tlc_stdout = "Error: Invariant SessionAtomicity is violated.\n"
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)
    run = ModelRun(config=config, expect_counterexample="SessionAtomicity")

    interpreted = run_model(root=tmp_path, jar=jar, run=run)
    raw = run_model(root=tmp_path, jar=jar, run=run, raw_exit=True)
    cli_raw = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "verification/tla/OutboxProtocol.cfg",
            "--raw-exit",
        ]
    )

    assert interpreted == 0
    assert raw == 12
    assert cli_raw == 12


def _violation_output(property_name: str, actions: Sequence[str]) -> str:
    lines = [
        f"Error: Invariant {property_name} is violated.\n",
        "Error: The behavior up to this point is:\n",
        "State 1: <Initial predicate>\n",
    ]
    for index, action in enumerate(actions, start=2):
        lines.append(
            f"State {index}: <{action} line 1, col 1 to line 2, col 1 of module SettlementCommit>\n"
        )
    return "".join(lines)


def _write_legacy_witness(path: Path, *, actions: Sequence[str]) -> Path:
    body = "\n".join(
        [
            "model: SettlementCommit",
            "config: SettlementCommitLegacy.cfg",
            "expected_violation: SessionAtomicity",
            "actions:",
            *[f"  - {name}" for name in actions],
            "durable: completed=true, cleared=false",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    return path


def test_expected_legacy_named_counterexample_is_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    witness = _write_legacy_witness(
        tmp_path / "SettlementCommitLegacy.trace",
        actions=("IssueCommand", "LegacyInsertCompleted"),
    )
    stub = _CommandStub()
    stub.tlc_returncode = 12
    stub.tlc_stdout = _violation_output(
        "SessionAtomicity",
        ("IssueCommand", "LegacyInsertCompleted"),
    )
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)
    run = ModelRun(
        config=config,
        expect_counterexample="SessionAtomicity",
        witness=witness,
    )

    exit_code = run_model(root=tmp_path, jar=jar, run=run)

    assert exit_code == 0


def test_legacy_model_unexpectedly_passing_fails_sensitivity_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    witness = _write_legacy_witness(
        tmp_path / "SettlementCommitLegacy.trace",
        actions=("IssueCommand", "LegacyInsertCompleted"),
    )
    stub = _CommandStub()
    stub.tlc_returncode = 0
    stub.tlc_stdout = "Model checking completed. No error has been found.\n"
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)
    run = ModelRun(
        config=config,
        expect_counterexample="SessionAtomicity",
        witness=witness,
    )

    exit_code = run_model(root=tmp_path, jar=jar, run=run)

    assert exit_code != 0


def test_legacy_violation_of_wrong_property_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    witness = _write_legacy_witness(
        tmp_path / "SettlementCommitLegacy.trace",
        actions=("IssueCommand", "LegacyInsertCompleted"),
    )
    stub = _CommandStub()
    stub.tlc_returncode = 12
    stub.tlc_stdout = _violation_output(
        "SessionIdempotency",
        ("IssueCommand", "LegacyInsertCompleted"),
    )
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)
    run = ModelRun(
        config=config,
        expect_counterexample="SessionAtomicity",
        witness=witness,
    )

    exit_code = run_model(root=tmp_path, jar=jar, run=run)

    assert exit_code != 0


def test_legacy_trace_without_committed_witness_actions_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    witness = _write_legacy_witness(
        tmp_path / "SettlementCommitLegacy.trace",
        actions=("IssueCommand", "LegacyInsertCompleted", "Crash"),
    )
    stub = _CommandStub()
    stub.tlc_returncode = 12
    stub.tlc_stdout = _violation_output(
        "SessionAtomicity",
        ("IssueCommand", "LegacyInsertCompleted"),
    )
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)
    run = ModelRun(
        config=config,
        expect_counterexample="SessionAtomicity",
        witness=witness,
    )

    exit_code = run_model(root=tmp_path, jar=jar, run=run)

    assert exit_code != 0


def test_current_model_any_counterexample_remains_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_tool_tree(tmp_path)
    jar = _seed_cached_jar(tmp_path)
    stub = _CommandStub()
    stub.tlc_returncode = 12
    stub.tlc_stdout = _violation_output(
        "SessionAtomicity",
        ("IssueCommand", "CommitComposite"),
    )
    monkeypatch.setattr(
        "scripts.check_formal_models._file_sha256",
        lambda path: _PINNED_SHA256,
    )
    monkeypatch.setattr("scripts.check_formal_models._run_command", stub)
    run = ModelRun(config=config)

    exit_code = run_model(root=tmp_path, jar=jar, run=run)

    assert exit_code != 0


def test_idempotent_effect_invariant_is_conditional_on_assumption() -> None:
    repo_cfg = Path(__file__).resolve().parents[2] / "verification" / "tla" / "OutboxProtocol.cfg"
    safety_cfg = repo_cfg.read_text(encoding="utf-8")

    assert "IdempotentEffectAtMostOnce" in safety_invariants(idempotency_enabled=True)
    assert "IdempotentEffectAtMostOnce" not in safety_invariants(idempotency_enabled=False)
    assert "IdempotencyEnabled = TRUE" in safety_cfg
    assert "INVARIANT IdempotentEffectAtMostOnce" in safety_cfg
    assert "WF_" not in safety_cfg
    assert "PROPERTY" not in safety_cfg
    assert "SPECIFICATION Spec" in safety_cfg
    assert "LivenessSpec" not in safety_cfg
