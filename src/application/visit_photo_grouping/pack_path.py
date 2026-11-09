from __future__ import annotations

from pathlib import Path

from beartype import beartype


@beartype
def validate_visit_photo_pack_key(pack_key: str) -> str:
    """Return stripped single-segment pack_key or raise ValueError."""
    key = pack_key.strip()
    if not key:
        raise ValueError("invalid pack_key")
    parts = Path(key).parts
    if len(parts) != 1 or parts[0] in {".", ".."} or Path(key).is_absolute():
        raise ValueError("invalid pack_key")
    return key


@beartype
def resolve_visit_photo_pack_dir(packs_root: Path, pack_key: str) -> Path:
    """Join packs root with a single-segment profile pack_key."""
    return packs_root / validate_visit_photo_pack_key(pack_key)
