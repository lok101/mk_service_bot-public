from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from beartype import beartype

from scripts.public_mirror_lib.rules import MirrorRules, load_patterns, select_paths

_DEFAULT_OVERLAY_TARGETS: tuple[str, ...] = (
    "README.md",
    ".env.example",
    "kit_platform_accounts.example.json",
    "kitvending_accounts.example.json",
)

_PUBLIC_MIRROR_NOTE = """# Public mirror

This tree is a sanitized public export of the private product repository.

- Internal documentation, operating model, ops runbooks, agent process corpus,
  task tracker files, and deployment guides are **not** included.
- Secrets, live account files, and local env files are never copied.
- Treat remaining `*.example` files as placeholders only.

Documentation is for internal use and is not part of this public mirror.
"""


@beartype
@dataclass(frozen=True, slots=True)
class MirrorPlan:
    copy_paths: tuple[str, ...]
    overlay_targets: tuple[str, ...]
    rules: MirrorRules


@beartype
@dataclass(frozen=True, slots=True)
class MirrorBuildResult:
    out_dir: Path
    copied: int
    overlays: tuple[str, ...]
    skipped_tracked: int


@beartype
def plan_mirror(
    *,
    repo_root: Path,
    tracked_paths: tuple[str, ...] | list[str],
    allow_file: Path,
    deny_file: Path,
    overlays_dir: Path,
    overlay_targets: tuple[str, ...] = _DEFAULT_OVERLAY_TARGETS,
) -> MirrorPlan:
    _ = repo_root
    rules = MirrorRules(
        allow=load_patterns(allow_file),
        deny=load_patterns(deny_file),
    )
    copy_paths = select_paths(tuple(tracked_paths), rules)
    existing_overlays = tuple(
        name
        for name in overlay_targets
        if (overlays_dir / name).is_file()
    )
    return MirrorPlan(
        copy_paths=copy_paths,
        overlay_targets=existing_overlays,
        rules=rules,
    )


@beartype
def _clear_mirror_tree(out_dir: Path) -> None:
    """Remove mirror contents but keep `.git` so remotes/history survive --force."""
    for child in out_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


@beartype
def apply_overlays(
    *,
    overlays_dir: Path,
    out_dir: Path,
    targets: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    written: list[str] = []
    for name in targets:
        source = overlays_dir / name
        if not source.is_file():
            continue
        destination = out_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        written.append(name.replace("\\", "/"))
    return tuple(written)


@beartype
def build_mirror(
    *,
    repo_root: Path,
    out_dir: Path,
    tracked_paths: tuple[str, ...] | list[str],
    allow_file: Path,
    deny_file: Path,
    overlays_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> MirrorBuildResult:
    repo_root = repo_root.resolve()
    out_dir = out_dir.resolve()
    if out_dir == repo_root or repo_root in out_dir.parents:
        msg = f"refusing to write mirror inside repo: {out_dir}"
        raise ValueError(msg)
    if out_dir.exists() and any(out_dir.iterdir()) and not force and not dry_run:
        msg = f"output directory is not empty (pass --force): {out_dir}"
        raise ValueError(msg)

    plan = plan_mirror(
        repo_root=repo_root,
        tracked_paths=tracked_paths,
        allow_file=allow_file,
        deny_file=deny_file,
        overlays_dir=overlays_dir,
    )
    tracked_count = len(tuple(tracked_paths))
    skipped = tracked_count - len(plan.copy_paths)

    if dry_run:
        return MirrorBuildResult(
            out_dir=out_dir,
            copied=len(plan.copy_paths),
            overlays=plan.overlay_targets,
            skipped_tracked=skipped,
        )

    if out_dir.exists() and force:
        _clear_mirror_tree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for rel in plan.copy_paths:
        source = repo_root / rel
        if not source.is_file():
            continue
        destination = out_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    overlays_written = apply_overlays(
        overlays_dir=overlays_dir,
        out_dir=out_dir,
        targets=plan.overlay_targets,
    )
    (out_dir / "PUBLIC_MIRROR.md").write_text(_PUBLIC_MIRROR_NOTE, encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "copied": len(plan.copy_paths),
        "overlays": list(overlays_written),
        "skipped_tracked": skipped,
        "allow_count": len(plan.rules.allow),
        "deny_count": len(plan.rules.deny),
    }
    (out_dir / "mirror-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return MirrorBuildResult(
        out_dir=out_dir,
        copied=len(plan.copy_paths),
        overlays=overlays_written,
        skipped_tracked=skipped,
    )
