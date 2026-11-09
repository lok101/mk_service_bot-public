from __future__ import annotations

from pathlib import Path

from .fakes import _codes, _pack_readme, _valid_fragment, _write


def test_pln013_new_pack_prose_fails(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-20-new-pack/README.md",
        _pack_readme(
            pack_dir_date="2026-07-20",
            fragment_rows="| `01-a.md` | a | — | ⏳ | — |",
            invariant_rows=("| notify path | `01-a.md` | handler tests |"),
        ),
    )
    _write(
        root,
        "docs/plans/2026-07-20-new-pack/01-a.md",
        _valid_fragment().replace("01: Test", "01: A"),
    )
    assert "PLN013" in _codes(root, readme)


def test_pln013_new_pack_exact_test_passes(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-20-new-pack-ok/README.md",
        _pack_readme(
            pack_dir_date="2026-07-20",
            fragment_rows="| `01-a.md` | a | — | ⏳ | — |",
            invariant_rows="| inv | `01-a.md` | `test_example_ok` |",
        ),
    )
    frag = _valid_fragment() + "\n`test_example_ok`\n"
    _write(root, "docs/plans/2026-07-20-new-pack-ok/01-a.md", frag)
    assert "PLN013" not in _codes(root, readme)


def test_pln013_active_old_closed_row_skipped(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-14-old-pack/README.md",
        _pack_readme(
            pack_dir_date="2026-07-14",
            fragment_rows=(
                "| `01-closed.md` | c | — | ✅ | ✅ |\n| `10-open.md` | o | — | ⏳ | — |"
            ),
            invariant_rows="| old inv | `01-closed.md` | handler tests |",
        ),
    )
    closed = _valid_fragment().replace("- [ ] **Шаг 1:** test", "- [x] **Шаг 1:** test")
    # Also close quality/self-check boxes so Status ✅ is not active via open `- [ ]`.
    closed = closed.replace("- [ ]", "- [x]")
    _write(root, "docs/plans/2026-07-14-old-pack/01-closed.md", closed)
    _write(
        root,
        "docs/plans/2026-07-14-old-pack/10-open.md",
        _valid_fragment().replace("01: Test", "10: Open"),
    )
    assert "PLN013" not in _codes(root, readme)


def test_pln013_active_old_active_row_without_test_fails(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-14-old-pack2/README.md",
        _pack_readme(
            pack_dir_date="2026-07-14",
            fragment_rows=(
                "| `01-closed.md` | c | — | ✅ | ✅ |\n| `10-open.md` | o | — | ⏳ | — |"
            ),
            invariant_rows="| notify | `10-open.md` | handler tests |",
        ),
    )
    _write(root, "docs/plans/2026-07-14-old-pack2/01-closed.md", _valid_fragment())
    _write(
        root,
        "docs/plans/2026-07-14-old-pack2/10-open.md",
        _valid_fragment().replace("01: Test", "10: Open"),
    )
    assert "PLN013" in _codes(root, readme)


def test_active_fragment_review_dash_not_active(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-14-review-dash/README.md",
        _pack_readme(
            pack_dir_date="2026-07-14",
            fragment_rows="| `09-done.md` | x | — | ✅ | — |",
            invariant_rows="| inv | `09-done.md` | handler tests |",
        ),
    )
    closed = _valid_fragment().replace("- [ ]", "- [x]")
    _write(root, "docs/plans/2026-07-14-review-dash/09-done.md", closed)
    assert "PLN013" not in _codes(root, readme)


def test_pln013_self_check_passes(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-20-self-check/README.md",
        _pack_readme(
            pack_dir_date="2026-07-20",
            fragment_rows="| `01-a.md` | a | — | ⏳ | — |",
            invariant_rows="| inv | `01-a.md` | self-check: grep collect-only |",
        ),
    )
    frag = _valid_fragment() + "\nself-check phrase: grep collect-only\n"
    _write(root, "docs/plans/2026-07-20-self-check/01-a.md", frag)
    assert "PLN013" not in _codes(root, readme)


def test_pln013_new_pack_glob_fails(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-20-glob-pack/README.md",
        _pack_readme(
            pack_dir_date="2026-07-20",
            fragment_rows="| `01-a.md` | a | — | ⏳ | — |",
            invariant_rows="| inv | `01-a.md` | `test_rehydrate_*` |",
        ),
    )
    _write(
        root,
        "docs/plans/2026-07-20-glob-pack/01-a.md",
        _valid_fragment() + "\n`test_rehydrate_ok`\n",
    )
    assert "PLN013" in _codes(root, readme)
