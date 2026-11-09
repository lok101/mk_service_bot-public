from __future__ import annotations

from pathlib import Path

from .fakes import _codes, _pack_readme, _single_plan_dated, _valid_fragment, _write


def test_pln014_outbox_without_runtime_path_fails(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-20-pln014-fail/README.md",
        _pack_readme(
            pack_dir_date="2026-07-20",
            fragment_rows="| `01-a.md` | a | — | ⏳ | — |",
            invariant_rows="| Success outbox notify | `01-a.md` | `test_handler_ok` |",
        ),
    )
    frag = _valid_fragment() + "\n`test_handler_ok`\n"
    _write(root, "docs/plans/2026-07-20-pln014-fail/01-a.md", frag)
    assert "PLN014" in _codes(root, readme) or "PLN014" in _codes(
        root, root / "docs/plans/2026-07-20-pln014-fail/01-a.md"
    )


def test_pln014_with_runtime_path_passes(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-20-pln014-ok/README.md",
        _pack_readme(
            pack_dir_date="2026-07-20",
            fragment_rows="| `01-a.md` | a | — | ⏳ | — |",
            invariant_rows="| Success outbox notify | `01-a.md` | `test_handler_ok` |",
        ),
    )
    frag = _valid_fragment() + "\n**Runtime path:** publish\n`test_handler_ok`\n"
    _write(root, "docs/plans/2026-07-20-pln014-ok/01-a.md", frag)
    codes = _codes(
        root,
        readme,
        root / "docs/plans/2026-07-20-pln014-ok/01-a.md",
    )
    assert "PLN014" not in codes


def test_pln014_single_plan_notify_without_marker_fails(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/2026-07-20-single-notify.md",
        _single_plan_dated(
            "2026-07-20",
            """## Задача 1: Wire telegram notify

**Файлы:**
- Изменить: `docs/notes.md`

- [ ] **Шаг 1:** add outbox notify handler docs
""",
        ),
    )
    assert "PLN014" in _codes(root, plan)


def test_pln014_single_plan_with_marker_passes(tmp_path: Path) -> None:
    root = tmp_path
    body = """**Runtime path:** integration

## Задача 1: Wire telegram notify

- [ ] **Шаг 1:** add outbox notify handler docs
"""
    plan = _write(
        root,
        "docs/plans/2026-07-20-single-notify-ok.md",
        _single_plan_dated("2026-07-20", body),
    )
    assert "PLN014" not in _codes(root, plan)


def test_runtime_gates_fully_closed_old_pack_skipped(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-14-fully-closed/README.md",
        _pack_readme(
            pack_dir_date="2026-07-14",
            fragment_rows="| `01-done.md` | x | — | ✅ | ✅ |",
            invariant_rows=("| Success outbox notify | `01-done.md` | handler tests |"),
        ),
    )
    closed = _valid_fragment().replace("- [ ]", "- [x]")
    closed = closed.replace(
        "**Глобальные инварианты из pack:** invariant one",
        "**Глобальные инварианты из pack:** outbox notify",
    )
    closed += """
## Задача 2: Удалить legacy port

- [x] **Шаг 1:** delete legacy module `ms_inventory_ports`
"""
    frag = _write(root, "docs/plans/2026-07-14-fully-closed/01-done.md", closed)
    codes = _codes(root, readme, frag)
    assert "PLN012" not in codes
    assert "PLN013" not in codes
    assert "PLN014" not in codes


def test_pln012_pln014_skipped_on_closed_fragment_in_active_pack(tmp_path: Path) -> None:
    root = tmp_path
    _write(
        root,
        "docs/plans/2026-07-14-mixed/README.md",
        _pack_readme(
            pack_dir_date="2026-07-14",
            fragment_rows=(
                "| `01-closed.md` | c | — | ✅ | ✅ |\n| `10-open.md` | o | — | ⏳ | — |"
            ),
            invariant_rows="| Success outbox notify | `10-open.md` | `test_handler_ok` |",
        ),
    )
    closed = _valid_fragment().replace("- [ ]", "- [x]")
    closed = closed.replace(
        "**Глобальные инварианты из pack:** invariant one",
        "**Глобальные инварианты из pack:** outbox notify path",
    )
    closed += """
## Задача 2: Удалить legacy port

- [x] **Шаг 1:** delete legacy module `ms_inventory_ports`
"""
    closed_path = _write(root, "docs/plans/2026-07-14-mixed/01-closed.md", closed)
    open_frag = (
        _valid_fragment().replace("01: Test", "10: Open")
        + "\n**Runtime path:** publish\n`test_handler_ok`\n"
    )
    _write(root, "docs/plans/2026-07-14-mixed/10-open.md", open_frag)
    codes = _codes(root, closed_path)
    assert "PLN012" not in codes
    assert "PLN014" not in codes


def test_fenced_open_checkbox_does_not_keep_fragment_active(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/2026-07-14-fenced/README.md",
        _pack_readme(
            pack_dir_date="2026-07-14",
            fragment_rows="| `09-done.md` | x | — | ✅ | — |",
            invariant_rows="| inv | `09-done.md` | handler tests |",
        ),
    )
    closed = _valid_fragment().replace("- [ ]", "- [x]")
    closed += """
Inline mention of `- [ ]` in docs must not keep fragment active.

```python
- [ ] example only inside fence
```
"""
    _write(root, "docs/plans/2026-07-14-fenced/09-done.md", closed)
    assert "PLN013" not in _codes(root, readme)
    assert "PLN007" not in _codes(root, readme)
