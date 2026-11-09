from __future__ import annotations

from pathlib import Path


def test_apb_index_lists_f1_f3_f4_and_optional_f2() -> None:
    readme = Path("verification/agent-process/problems/README.md").read_text(encoding="utf-8")
    assert "APB-0001-mcp-nav-prefix" in readme
    assert "APB-0003-lifecycle-recover-deny" in readme
    assert "APB-0004-residue-closeout" in readme
    # F2 optional but promoted when signature stable.
    assert "APB-0002-cross-contract-ux" in readme
    assert "_(empty until first promote)_" not in readme

    for stem in (
        "APB-0001-mcp-nav-prefix",
        "APB-0002-cross-contract-ux",
        "APB-0003-lifecycle-recover-deny",
        "APB-0004-residue-closeout",
    ):
        path = Path("verification/agent-process/problems") / f"{stem}.md"
        assert path.is_file()
        body = path.read_text(encoding="utf-8")
        assert "**status:**" in body
        assert "**signatures:**" in body
        assert "apr-" in body
