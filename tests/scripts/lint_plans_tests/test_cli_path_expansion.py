from __future__ import annotations

from pathlib import Path

from scripts.lint_plans import _expand_cli_paths, lint_plan_paths

from .fakes import _valid_fragment, _write


def _resolved_names(paths: tuple[Path, ...]) -> set[str]:
    return {path.name for path in paths}


def test_pack_readme_path_expands_to_sibling_markdown(tmp_path: Path) -> None:
    root = tmp_path
    _write(root, "docs/plans/pack/README.md", "# Pack\n")
    _write(root, "docs/plans/pack/01-domain.md", _valid_fragment())

    expanded = _expand_cli_paths(root, ("docs/plans/pack/README.md",))

    assert _resolved_names(expanded) == {"README.md", "01-domain.md"}


def test_root_plans_readme_path_does_not_expand(tmp_path: Path) -> None:
    root = tmp_path
    _write(root, "docs/plans/README.md", "# Plans index\n")
    _write(root, "docs/plans/2026-07-09-single.md", "# Single\n")

    expanded = _expand_cli_paths(root, ("docs/plans/README.md",))

    assert _resolved_names(expanded) == {"README.md"}


def test_fragment_path_does_not_expand_to_siblings(tmp_path: Path) -> None:
    root = tmp_path
    _write(root, "docs/plans/pack/README.md", "# Pack\n")
    _write(root, "docs/plans/pack/01-domain.md", _valid_fragment())
    _write(
        root,
        "docs/plans/pack/02-other.md",
        _valid_fragment().replace("01: Test", "02: Other"),
    )

    expanded = _expand_cli_paths(root, ("docs/plans/pack/01-domain.md",))

    assert _resolved_names(expanded) == {"01-domain.md"}


def test_pack_readme_path_lints_wide_fragment(tmp_path: Path) -> None:
    root = tmp_path
    _write(root, "docs/plans/pack/README.md", "# Pack\n\n## Routing Gate\n")
    task_blocks = "\n\n".join(f"## Задача {index}: Test\n" for index in range(1, 10))
    fragment = _write(
        root,
        "docs/plans/pack/01-domain.md",
        _valid_fragment().replace("## Задача 1: Test task", task_blocks),
    )

    paths = _expand_cli_paths(root, ("docs/plans/pack/README.md",))
    violations = lint_plan_paths(root, paths=paths)

    assert any(
        violation.code == "PLN005" and violation.path.resolve() == fragment.resolve()
        for violation in violations
    )


def test_lint_plans_entrypoint_reexports_public_api() -> None:
    from scripts.lint_plans import PlanViolation, _expand_cli_paths, lint_plan_paths

    assert callable(lint_plan_paths)
    assert callable(_expand_cli_paths)
    assert PlanViolation.__name__ == "PlanViolation"
