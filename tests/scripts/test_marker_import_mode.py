from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PATHS = (
    _ROOT / "scripts/integration-check.sh",
    _ROOT / "scripts/e2e-flow-check.sh",
    _ROOT / "scripts/e2e-flow-check.ps1",
    _ROOT / "AGENTS.md",
)


def test_marker_scripts_keep_importlib() -> None:
    for path in _PATHS:
        text = path.read_text(encoding="utf-8")
        matched = False
        for line in text.splitlines():
            if "pytest" not in line or "-o addopts=" not in line:
                continue
            matched = True
            assert "--import-mode=importlib" in line, path
        assert matched, path
