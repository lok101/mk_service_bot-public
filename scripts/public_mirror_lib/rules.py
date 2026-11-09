from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class MirrorRules:
    allow: tuple[str, ...]
    deny: tuple[str, ...]


@beartype
def load_patterns(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    patterns: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line.replace("\\", "/"))
    return tuple(patterns)


@beartype
def normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


@beartype
def path_matches(path: str, pattern: str) -> bool:
    normalized = normalize_repo_path(path)
    pat = pattern.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.full_match(pat):
        return True
    # Directory-style patterns like `src/**` should also match the directory itself.
    if pat.endswith("/**"):
        prefix = pat[:-3]
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


@beartype
def path_allowed(path: str, rules: MirrorRules) -> bool:
    normalized = normalize_repo_path(path)
    if not any(path_matches(normalized, pattern) for pattern in rules.allow):
        return False
    return not any(path_matches(normalized, pattern) for pattern in rules.deny)


@beartype
def select_paths(paths: tuple[str, ...] | list[str], rules: MirrorRules) -> tuple[str, ...]:
    selected = [normalize_repo_path(path) for path in paths if path_allowed(path, rules)]
    return tuple(selected)
