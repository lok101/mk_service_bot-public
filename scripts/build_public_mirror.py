#!/usr/bin/env python3
"""Build a sanitized public mirror tree (allowlist + overlays).

Example:
  uv run python scripts/build_public_mirror.py --out ../mk_service_bot-public --force
  uv run python scripts/build_public_mirror.py --out ../mk_service_bot-public --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from beartype import beartype  # noqa: E402

from scripts.public_mirror_lib.build import build_mirror  # noqa: E402


@beartype
def _repo_root() -> Path:
    return _ROOT


@beartype
def _candidate_repo_paths(repo_root: Path) -> tuple[str, ...]:
    """Tracked + untracked non-ignored paths (never gitignored secrets)."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-zco", "--exclude-standard"],
        check=True,
        capture_output=True,
    )
    raw = completed.stdout.split(b"\0")
    paths = sorted({item.decode("utf-8").replace("\\", "/") for item in raw if item})
    return tuple(paths)


@beartype
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a sanitized public mirror from git-tracked and untracked "
            "non-ignored files (allowlist + deny + overlays)."
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory outside the private repo",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace non-empty output directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan only; do not write files",
    )
    parser.add_argument(
        "--allow",
        type=Path,
        default=None,
        help="Path to mirror.allow (default: scripts/public_mirror/mirror.allow)",
    )
    parser.add_argument(
        "--deny",
        type=Path,
        default=None,
        help="Path to mirror.deny (default: scripts/public_mirror/mirror.deny)",
    )
    parser.add_argument(
        "--overlays",
        type=Path,
        default=None,
        help="Overlays directory (default: scripts/public_mirror/overlays)",
    )
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    conf = repo_root / "scripts" / "public_mirror"
    allow_file = args.allow or (conf / "mirror.allow")
    deny_file = args.deny or (conf / "mirror.deny")
    overlays_dir = args.overlays or (conf / "overlays")

    candidates = _candidate_repo_paths(repo_root)
    result = build_mirror(
        repo_root=repo_root,
        out_dir=args.out,
        tracked_paths=candidates,
        allow_file=allow_file,
        deny_file=deny_file,
        overlays_dir=overlays_dir,
        force=args.force,
        dry_run=args.dry_run,
    )

    mode = "dry-run" if args.dry_run else "wrote"
    print(
        f"public mirror {mode}: copied={result.copied} "
        f"overlays={len(result.overlays)} skipped_tracked={result.skipped_tracked} "
        f"out={result.out_dir}",
    )
    if result.overlays:
        print("overlays: " + ", ".join(result.overlays))
    return 0


if __name__ == "__main__":
    sys.exit(main())
