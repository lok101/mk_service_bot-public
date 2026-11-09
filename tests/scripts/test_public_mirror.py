from __future__ import annotations

from pathlib import Path

from scripts.public_mirror_lib.build import (
    apply_overlays,
    build_mirror,
    plan_mirror,
)
from scripts.public_mirror_lib.rules import (
    MirrorRules,
    load_patterns,
    select_paths,
)


def test_normalize_preserves_leading_dotfiles() -> None:
    from scripts.public_mirror_lib.rules import normalize_repo_path, path_matches

    assert normalize_repo_path("./.gitignore") == ".gitignore"
    assert path_matches(".gitignore", ".gitignore")


def test_load_patterns_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "mirror.allow"
    path.write_text(
        "# comment\n\nsrc/**\n  tests/**  \n",
        encoding="utf-8",
    )

    assert load_patterns(path) == ("src/**", "tests/**")


def test_select_paths_default_deny_allow_then_deny() -> None:
    rules = MirrorRules(
        allow=("src/**", "tests/**", "README.md"),
        deny=("tests/integration/*_live/**", "docs/**"),
    )
    paths = (
        "src/domain/x.py",
        "tests/domain/test_x.py",
        "tests/integration/kitvending_live/test_y.py",
        "docs/architecture.md",
        "README.md",
        "scripts/secret_admin.py",
    )

    assert select_paths(paths, rules) == (
        "src/domain/x.py",
        "tests/domain/test_x.py",
        "README.md",
    )


def test_plan_mirror_uses_overlays_instead_of_private_readme(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    overlays = repo / "scripts" / "public_mirror" / "overlays"
    overlays.mkdir(parents=True)
    (overlays / "README.md").write_text("PUBLIC\n", encoding="utf-8")
    (overlays / ".env.example").write_text("BOT_TOKEN=\n", encoding="utf-8")
    allow = repo / "scripts" / "public_mirror" / "mirror.allow"
    deny = repo / "scripts" / "public_mirror" / "mirror.deny"
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text("src/**\n", encoding="utf-8")
    deny.write_text("", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x\n", encoding="utf-8")

    plan = plan_mirror(
        repo_root=repo,
        tracked_paths=("src/a.py", "README.md", ".env.dev.example"),
        allow_file=allow,
        deny_file=deny,
        overlays_dir=overlays,
    )

    assert plan.copy_paths == ("src/a.py",)
    assert set(plan.overlay_targets) == {"README.md", ".env.example"}


def test_build_mirror_copies_and_overlays(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "public"
    overlays = repo / "scripts" / "public_mirror" / "overlays"
    overlays.mkdir(parents=True)
    (overlays / "README.md").write_text("# Public\n", encoding="utf-8")
    (overlays / "kit_platform_accounts.example.json").write_text(
        '[{"account_key":"vending-demo"}]\n',
        encoding="utf-8",
    )
    allow = repo / "scripts" / "public_mirror" / "mirror.allow"
    deny = repo / "scripts" / "public_mirror" / "mirror.deny"
    allow.write_text(
        "src/**\nkit_platform_accounts.example.json\n",
        encoding="utf-8",
    )
    deny.write_text("", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    (repo / "kit_platform_accounts.example.json").write_text(
        '[{"account_key":"vending-head-private"}]\n',
        encoding="utf-8",
    )

    result = build_mirror(
        repo_root=repo,
        out_dir=out,
        tracked_paths=("src/a.py", "kit_platform_accounts.example.json"),
        allow_file=allow,
        deny_file=deny,
        overlays_dir=overlays,
        force=True,
    )

    assert result.copied == 2
    assert (out / "src" / "a.py").read_text(encoding="utf-8") == "print(1)\n"
    assert (out / "README.md").read_text(encoding="utf-8") == "# Public\n"
    assert "vending-head-private" not in (
        out / "kit_platform_accounts.example.json"
    ).read_text(encoding="utf-8")
    assert "vending-demo" in (
        out / "kit_platform_accounts.example.json"
    ).read_text(encoding="utf-8")
    assert (out / "PUBLIC_MIRROR.md").is_file()
    assert (out / "mirror-manifest.json").is_file()


def test_build_mirror_force_preserves_git_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "public"
    overlays = repo / "scripts" / "public_mirror" / "overlays"
    overlays.mkdir(parents=True)
    (overlays / "README.md").write_text("# Public\n", encoding="utf-8")
    allow = repo / "scripts" / "public_mirror" / "mirror.allow"
    deny = repo / "scripts" / "public_mirror" / "mirror.deny"
    allow.write_text("src/**\n", encoding="utf-8")
    deny.write_text("", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    out.mkdir()
    (out / "stale.txt").write_text("old\n", encoding="utf-8")
    git_dir = out / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")

    build_mirror(
        repo_root=repo,
        out_dir=out,
        tracked_paths=("src/a.py",),
        allow_file=allow,
        deny_file=deny,
        overlays_dir=overlays,
        force=True,
    )

    assert not (out / "stale.txt").exists()
    assert (out / ".git" / "HEAD").read_text(encoding="utf-8") == (
        "ref: refs/heads/master\n"
    )
    assert (out / "src" / "a.py").is_file()


def test_apply_overlays_writes_only_named_files(tmp_path: Path) -> None:
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "README.md").write_text("ok\n", encoding="utf-8")
    (overlays / "notes.txt").write_text("skip\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    written = apply_overlays(
        overlays_dir=overlays,
        out_dir=out,
        targets=("README.md",),
    )

    assert written == ("README.md",)
    assert (out / "README.md").read_text(encoding="utf-8") == "ok\n"
    assert not (out / "notes.txt").exists()
