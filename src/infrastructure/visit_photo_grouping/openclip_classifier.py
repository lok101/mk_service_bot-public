from __future__ import annotations

import hashlib
import json
import logging
import math
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.application.visit_photo_grouping.ports import (
    GroupingGroup,
    GroupingPermanentFailure,
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
)
from src.application.visit_photo_review import POOR_QUALITY_GROUP_ID, UNRECOGNIZED_GROUP_ID

_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_RESERVED_GROUP_IDS = frozenset({UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID})
_MARGIN_FLOOR = 0.02
_SCORE_PERCENTILE = 0.2
_CACHE_VERSION = 1
_CACHE_RELATIVE = Path(".cache") / "openclip_reference_prototypes.v1.json"
_DEFAULT_ENCODER_ID = "open_clip:ViT-B-32:laion2b_s34b_b79k"

logger = logging.getLogger(__name__)


@runtime_checkable
class ImageBytesEncoder(Protocol):
    def encode(self, image_bytes: bytes) -> tuple[float, ...]: ...


@runtime_checkable
class PhotoBytesReader(Protocol):
    def get_bytes(self, storage_key: str) -> bytes: ...


def open_clip_encoder_id(*, weights_path: str = "") -> str:
    stripped = weights_path.strip()
    if stripped:
        return f"open_clip:ViT-B-32:file:{stripped}"
    return _DEFAULT_ENCODER_ID


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = fraction * (len(sorted_values) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return sorted_values[low]
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _load_reference_paths(pack_dir: Path) -> dict[str, tuple[Path, ...]]:
    reference = pack_dir / "reference"
    if not reference.is_dir():
        raise ValueError(f"pack reference directory missing: {reference}")
    groups: dict[str, list[Path]] = {}
    for group_dir in sorted(reference.iterdir()):
        if not group_dir.is_dir() or group_dir.name in _RESERVED_GROUP_IDS:
            continue
        images = tuple(
            sorted(
                path
                for path in group_dir.iterdir()
                if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
            )
        )
        if images:
            groups[group_dir.name] = list(images)
    if not groups:
        raise ValueError(
            "VISIT_PHOTO_GROUPING_PACK_DIR/reference must contain at least "
            "one group directory with image files",
        )
    return {group_id: tuple(paths) for group_id, paths in groups.items()}


def _compute_thresholds(
    prototypes: Mapping[str, tuple[tuple[float, ...], ...]],
) -> tuple[float, float]:
    best_scores: list[float] = []
    margins: list[float] = []
    for group_id, vectors in prototypes.items():
        for index, vector in enumerate(vectors):
            scores: list[float] = []
            for other_id, other_vectors in prototypes.items():
                candidates = other_vectors
                if other_id == group_id:
                    candidates = tuple(item for i, item in enumerate(other_vectors) if i != index)
                    if not candidates:
                        continue
                scores.append(max(_cosine(vector, item) for item in candidates))
            if not scores:
                continue
            ordered = sorted(scores, reverse=True)
            best = ordered[0]
            second = ordered[1] if len(ordered) > 1 else 0.0
            best_scores.append(best)
            margins.append(best - second)
    best_scores.sort()
    margins.sort()
    min_score = _percentile(best_scores, _SCORE_PERCENTILE) if best_scores else 0.0
    raw_margin = _percentile(margins, _SCORE_PERCENTILE) if margins else _MARGIN_FLOOR
    return min_score, max(_MARGIN_FLOOR, raw_margin)


def _relative_key(pack_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(pack_dir.resolve()).as_posix()


def _file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.stat().st_size}:{digest}"


def _build_file_fingerprints(
    pack_dir: Path,
    paths_by_group: Mapping[str, tuple[Path, ...]],
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for paths in paths_by_group.values():
        for path in paths:
            fingerprints[_relative_key(pack_dir, path)] = _file_fingerprint(path)
    return fingerprints


def _cache_path(pack_dir: Path) -> Path:
    return pack_dir / _CACHE_RELATIVE


def _load_prototype_cache(
    *,
    pack_dir: Path,
    encoder_id: str,
    fingerprints: Mapping[str, str],
) -> tuple[dict[str, tuple[tuple[float, ...], ...]], float, float] | None:
    path = _cache_path(pack_dir)
    if not path.is_file():
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != _CACHE_VERSION:
        return None
    if payload.get("encoder_id") != encoder_id:
        return None
    cached_files = payload.get("files")
    if not isinstance(cached_files, dict) or cached_files != dict(fingerprints):
        return None
    raw_prototypes = payload.get("prototypes")
    min_score = payload.get("min_score")
    min_margin = payload.get("min_margin")
    if not isinstance(raw_prototypes, dict):
        return None
    if not isinstance(min_score, (int, float)) or not isinstance(min_margin, (int, float)):
        return None
    prototypes: dict[str, tuple[tuple[float, ...], ...]] = {}
    try:
        for group_id, vectors in raw_prototypes.items():
            if not isinstance(group_id, str) or not isinstance(vectors, list):
                return None
            parsed = tuple(tuple(float(value) for value in vector) for vector in vectors)
            prototypes[group_id] = parsed
    except TypeError, ValueError:
        return None
    expected_groups = {key.split("/", 2)[1] for key in fingerprints if key.startswith("reference/")}
    if set(prototypes) != expected_groups:
        return None
    return prototypes, float(min_score), float(min_margin)


def _write_prototype_cache(
    *,
    pack_dir: Path,
    encoder_id: str,
    fingerprints: Mapping[str, str],
    prototypes: Mapping[str, tuple[tuple[float, ...], ...]],
    min_score: float,
    min_margin: float,
) -> None:
    path = _cache_path(pack_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _CACHE_VERSION,
        "encoder_id": encoder_id,
        "files": dict(fingerprints),
        "prototypes": {
            group_id: [list(vector) for vector in vectors]
            for group_id, vectors in sorted(prototypes.items())
        },
        "min_score": min_score,
        "min_margin": min_margin,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as handle:
            handle.write(encoded)
            temp_name = handle.name
        Path(temp_name).replace(path)
    except OSError:
        return


@beartype
@dataclass(slots=True)
class OpenClipGroupClassifier:
    pack_dir: Path
    storage: PhotoBytesReader
    encoder: ImageBytesEncoder
    min_score: float | None = None
    min_margin: float | None = None
    encoder_id: str = _DEFAULT_ENCODER_ID
    use_prototype_cache: bool = True
    _prototypes: dict[str, tuple[tuple[float, ...], ...]] = field(
        init=False,
        repr=False,
    )
    _fingerprints: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        pack_dir = Path(self.pack_dir)
        paths_by_group = _load_reference_paths(pack_dir)
        fingerprints = _build_file_fingerprints(pack_dir, paths_by_group)
        cached: tuple[dict[str, tuple[tuple[float, ...], ...]], float, float] | None = None
        if self.use_prototype_cache:
            cached = _load_prototype_cache(
                pack_dir=pack_dir,
                encoder_id=self.encoder_id,
                fingerprints=fingerprints,
            )
        if cached is not None:
            prototypes, cached_score, cached_margin = cached
            self._prototypes = prototypes
            self._fingerprints = dict(fingerprints)
            if self.min_score is None:
                self.min_score = cached_score
            if self.min_margin is None:
                self.min_margin = cached_margin
            return
        prototypes = {
            group_id: tuple(self.encoder.encode(path.read_bytes()) for path in paths)
            for group_id, paths in paths_by_group.items()
        }
        self._prototypes = prototypes
        self._fingerprints = dict(fingerprints)
        if self.min_score is None or self.min_margin is None:
            computed_score, computed_margin = _compute_thresholds(prototypes)
            if self.min_score is None:
                self.min_score = computed_score
            if self.min_margin is None:
                self.min_margin = computed_margin
        assert self.min_score is not None
        assert self.min_margin is not None
        if self.use_prototype_cache:
            _write_prototype_cache(
                pack_dir=pack_dir,
                encoder_id=self.encoder_id,
                fingerprints=fingerprints,
                prototypes=prototypes,
                min_score=self.min_score,
                min_margin=self.min_margin,
            )

    def _persist_prototype_cache(self, pack_dir: Path) -> None:
        if not self.use_prototype_cache:
            return
        assert self.min_score is not None
        assert self.min_margin is not None
        _write_prototype_cache(
            pack_dir=pack_dir,
            encoder_id=self.encoder_id,
            fingerprints=self._fingerprints,
            prototypes=self._prototypes,
            min_score=self.min_score,
            min_margin=self.min_margin,
        )

    def _cold_reload_prototypes(
        self,
        pack_dir: Path,
        paths_by_group: Mapping[str, tuple[Path, ...]],
        fingerprints: Mapping[str, str],
    ) -> None:
        self._prototypes = {
            group_id: tuple(self.encoder.encode(path.read_bytes()) for path in paths)
            for group_id, paths in paths_by_group.items()
        }
        self._fingerprints = dict(fingerprints)
        self._persist_prototype_cache(pack_dir)

    def _ensure_prototypes_current(self) -> None:
        pack_dir = Path(self.pack_dir)
        paths_by_group = _load_reference_paths(pack_dir)
        current = _build_file_fingerprints(pack_dir, paths_by_group)
        if current == self._fingerprints:
            return
        added_keys = sorted(key for key in current if key not in self._fingerprints)
        removed_or_changed = any(
            key not in current or current[key] != fingerprint
            for key, fingerprint in self._fingerprints.items()
        )
        if removed_or_changed:
            self._cold_reload_prototypes(pack_dir, paths_by_group, current)
            return
        for rel_key in added_keys:
            path = pack_dir / rel_key
            group_id = Path(rel_key).parts[1]
            vector = self.encoder.encode(path.read_bytes())
            self._prototypes[group_id] = (*self._prototypes.get(group_id, ()), vector)
        self._fingerprints = dict(current)
        logger.info(
            "visit_photo_grouping.prototypes_reloaded",
            extra={"added": len(added_keys)},
        )
        self._persist_prototype_cache(pack_dir)

    @beartype
    def classify(
        self,
        batch_id: str,
        files: tuple[GroupingStoredFile, ...],
    ) -> GroupingSuccess | GroupingTemporaryFailure | GroupingPermanentFailure:
        del batch_id
        self._ensure_prototypes_current()
        assigned: dict[str, list[int]] = {}
        for item in files:
            try:
                payload = self.storage.get_bytes(item.storage_key)
            except FileNotFoundError, OSError, KeyError, ValueError:
                return GroupingTemporaryFailure()
            try:
                vector = self.encoder.encode(payload)
            except Exception:
                return GroupingTemporaryFailure()
            scores = {
                group_id: max(_cosine(vector, prototype) for prototype in prototypes)
                for group_id, prototypes in self._prototypes.items()
            }
            if not scores:
                return GroupingPermanentFailure()
            ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
            best_id, best_score = ordered[0]
            second_score = ordered[1][1] if len(ordered) > 1 else 0.0
            assert self.min_score is not None
            assert self.min_margin is not None
            if best_score < self.min_score or (best_score - second_score) < self.min_margin:
                continue
            if best_id in _RESERVED_GROUP_IDS:
                continue
            assigned.setdefault(best_id, []).append(item.index)
        groups = tuple(
            GroupingGroup(group_id=group_id, indexes=tuple(sorted(indexes)))
            for group_id, indexes in sorted(assigned.items())
        )
        return GroupingSuccess(groups=groups)


def build_open_clip_encoder(
    *,
    weights_path: str = "",
) -> ImageBytesEncoder:
    """Lazy OpenCLIP encoder; imports torch/open_clip only when constructed."""

    @beartype
    @dataclass(slots=True)
    class _OpenClipEncoder:
        _encode_fn: Callable[[bytes], tuple[float, ...]]

        def encode(self, image_bytes: bytes) -> tuple[float, ...]:
            return self._encode_fn(image_bytes)

    import io

    import open_clip
    import torch
    from PIL import Image

    pretrained: str | Path = Path(weights_path) if weights_path.strip() else "laion2b_s34b_b79k"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32",
        pretrained=str(pretrained),
    )
    model.eval()

    def _encode(image_bytes: bytes) -> tuple[float, ...]:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = preprocess(image).unsqueeze(0)
        with torch.no_grad():
            features = model.encode_image(tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return tuple(float(value) for value in features[0].tolist())

    return _OpenClipEncoder(_encode_fn=_encode)
