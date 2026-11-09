from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.agent_process_eval_lib.baseline import (
    BaselineLockedError,
    load_baseline,
    write_baseline,
)
from scripts.agent_process_eval_lib.compare import compare_to_baseline
from scripts.agent_process_eval_lib.paths import live_results_dir, unique_loaded_bytes
from scripts.run_agent_process_evals import main


def test_cutover_compare_requires_context_reduction() -> None:
    ok = compare_to_baseline(
        baseline={"median_loaded_bytes": 1000, "safety_pass": True},
        candidate={"median_loaded_bytes": 600, "safety_pass": True},
        min_context_reduction=0.40,
    )
    assert ok.ok is True
    bad = compare_to_baseline(
        baseline={"median_loaded_bytes": 1000, "safety_pass": True},
        candidate={"median_loaded_bytes": 900, "safety_pass": True},
        min_context_reduction=0.40,
    )
    assert bad.ok is False


def test_write_baseline_without_flag_raises(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        '{"schema_version":1,"process":"legacy","recorded_for":"x","metrics":{}}',
        encoding="utf-8",
    )
    with pytest.raises(BaselineLockedError, match="update-baseline"):
        write_baseline(path, load_baseline(path), update=False)


def test_write_baseline_with_flag_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    original = {
        "schema_version": 1,
        "process": "legacy",
        "recorded_for": "pre-cutover-worker-skills",
        "metrics": {"median_human_stops": 2},
    }
    write_baseline(path, original, update=True)
    updated = dict(original)
    updated["metrics"] = {"median_human_stops": 1}
    write_baseline(path, updated, update=True)
    assert load_baseline(path)["metrics"]["median_human_stops"] == 1


def test_live_results_dir_under_git_common_agent_evals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    monkeypatch.setattr(
        "scripts.agent_process_eval_lib.paths.git_common_dir",
        lambda _cwd=None: common,
    )
    target = live_results_dir(run_id="run-1")
    assert target == common / "agent-evals" / "run-1"
    assert "verification" not in target.parts


def test_unique_loaded_bytes_counts_each_path_once(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("aa", encoding="utf-8")
    b.write_text("bbbb", encoding="utf-8")
    total = unique_loaded_bytes([a, b, a])
    assert total == a.stat().st_size + b.stat().st_size


def test_cli_run_corpus_exits_zero() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/run_agent_process_evals.py",
            "--corpus",
            "verification/agent-process",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "01-readonly" in proc.stdout


def test_update_baseline_preserves_legacy_median_human_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "fixtures").mkdir(parents=True)
    (corpus / "expected").mkdir()
    fixture = {
        "schema_version": 1,
        "id": "01-readonly",
        "title": "t",
        "process": "legacy",
        "events": [{"kind": "classify", "payload": {"mode": "read_only"}}],
    }
    (corpus / "fixtures" / "01-readonly.json").write_text(json.dumps(fixture), encoding="utf-8")
    (corpus / "expected" / "01-readonly.json").write_text(
        json.dumps({"ok": True, "human_stops": 0}), encoding="utf-8"
    )
    baseline = {
        "schema_version": 1,
        "process": "legacy",
        "recorded_for": "pre-cutover-worker-skills",
        "metrics": {
            "median_loaded_process_context_bytes": 2500000,
            "outcome_success_rate": 1.0,
            "safety_predicate_failures": 0,
            "median_human_stops": 2,
        },
    }
    (corpus / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    assert main(["--corpus", str(corpus), "--update-baseline"]) == 0
    updated = json.loads((corpus / "baseline.json").read_text(encoding="utf-8"))
    assert updated["metrics"]["median_human_stops"] == 2
    assert updated["metrics"]["median_loaded_process_context_bytes"] == 2500000


def test_update_baseline_counts_model_check_gate_failure(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "fixtures").mkdir(parents=True)
    (corpus / "expected").mkdir()
    fixture = {
        "schema_version": 1,
        "id": "14-omc-skip-implementing",
        "title": "skip",
        "process": "operating-model-case-check",
        "events": [
            {"kind": "state", "payload": {"state": "planning"}},
            {"kind": "state", "payload": {"state": "implementing"}},
        ],
    }
    (corpus / "fixtures" / "14-omc-skip-implementing.json").write_text(
        json.dumps(fixture), encoding="utf-8"
    )
    (corpus / "expected" / "14-omc-skip-implementing.json").write_text(
        json.dumps({"ok": False, "failures": ["model_check_gate"]}),
        encoding="utf-8",
    )
    assert main(["--corpus", str(corpus), "--update-baseline"]) == 0
    updated = json.loads((corpus / "baseline.json").read_text(encoding="utf-8"))
    assert updated["metrics"]["safety_predicate_failures"] == 1
    assert updated["metrics"]["outcome_success_rate"] == 0.0
