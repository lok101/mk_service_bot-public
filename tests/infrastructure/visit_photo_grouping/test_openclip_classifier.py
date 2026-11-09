from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.application.visit_photo_grouping.ports import (
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
)
from src.application.visit_photo_review import POOR_QUALITY_GROUP_ID, UNRECOGNIZED_GROUP_ID
from src.infrastructure.visit_photo_grouping.openclip_classifier import (
    OpenClipGroupClassifier,
)


@dataclass(frozen=True, slots=True)
class _StubEncoder:
    vectors: dict[bytes, tuple[float, ...]]

    def encode(self, image_bytes: bytes) -> tuple[float, ...]:
        try:
            return self.vectors[image_bytes]
        except KeyError as exc:
            raise RuntimeError(f"missing stub vector for {image_bytes!r}") from exc


@dataclass(frozen=True, slots=True)
class _StubStorage:
    objects: dict[str, bytes]

    def get_bytes(self, storage_key: str) -> bytes:
        try:
            return self.objects[storage_key]
        except KeyError as exc:
            raise FileNotFoundError(storage_key) from exc


def _pack_two_groups(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    for group_id, name in (("door", b"ref-door"), ("display", b"ref-display")):
        group_dir = pack / "reference" / group_id
        group_dir.mkdir(parents=True)
        (group_dir / f"{group_id}.jpg").write_bytes(name)
    return pack


def _file(index: int, key: str) -> GroupingStoredFile:
    return GroupingStoredFile(
        index=index,
        storage_key=key,
        content_type="image/jpeg",
        content_hash=f"hash-{index}",
    )


def test_classify_assigns_two_files_to_groups(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    encoder = _StubEncoder(
        {
            b"ref-door": (1.0, 0.0),
            b"ref-display": (0.0, 1.0),
            b"photo-door": (0.99, 0.01),
            b"photo-display": (0.01, 0.99),
        },
    )
    storage = _StubStorage(
        {
            "k0": b"photo-door",
            "k1": b"photo-display",
        },
    )
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=storage,
        encoder=encoder,
        min_score=0.5,
        min_margin=0.02,
    )
    result = classifier.classify(
        "batch-1",
        (_file(0, "k0"), _file(1, "k1")),
    )
    assert isinstance(result, GroupingSuccess)
    by_id = {group.group_id: group.indexes for group in result.groups}
    assert by_id == {"door": (0,), "display": (1,)}
    assert UNRECOGNIZED_GROUP_ID not in by_id
    assert POOR_QUALITY_GROUP_ID not in by_id


def test_classify_omits_low_margin_index(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    encoder = _StubEncoder(
        {
            b"ref-door": (1.0, 0.0),
            b"ref-display": (0.0, 1.0),
            b"ambiguous": (0.55, 0.54),
        },
    )
    storage = _StubStorage({"k0": b"ambiguous"})
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=storage,
        encoder=encoder,
        min_score=0.5,
        min_margin=0.05,
    )
    result = classifier.classify("batch-1", (_file(0, "k0"),))
    assert isinstance(result, GroupingSuccess)
    assert result.groups == ()


def test_classify_storage_miss_is_temporary_failure(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    encoder = _StubEncoder(
        {
            b"ref-door": (1.0, 0.0),
            b"ref-display": (0.0, 1.0),
        },
    )
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=encoder,
        min_score=0.5,
        min_margin=0.02,
    )
    result = classifier.classify("batch-1", (_file(0, "missing"),))
    assert isinstance(result, GroupingTemporaryFailure)


def test_thresholds_computed_from_references(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    for group_id, payloads in (
        ("door", (b"ref-door-a", b"ref-door-b")),
        ("display", (b"ref-display-a", b"ref-display-b")),
    ):
        group_dir = pack / "reference" / group_id
        group_dir.mkdir(parents=True)
        for index, payload in enumerate(payloads):
            (group_dir / f"{group_id}-{index}.jpg").write_bytes(payload)
    encoder = _StubEncoder(
        {
            b"ref-door-a": (1.0, 0.05),
            b"ref-door-b": (0.98, 0.02),
            b"ref-display-a": (0.05, 1.0),
            b"ref-display-b": (0.02, 0.97),
        },
    )
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=encoder,
    )
    assert classifier.min_score is not None and classifier.min_score > 0.5
    assert classifier.min_margin is not None and classifier.min_margin >= 0.02


def test_model_never_emits_reserved_ids(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    reserved_dir = pack / "reference" / UNRECOGNIZED_GROUP_ID
    reserved_dir.mkdir()
    (reserved_dir / "bad.jpg").write_bytes(b"ref-unrecognized")
    encoder = _StubEncoder(
        {
            b"ref-door": (1.0, 0.0),
            b"ref-display": (0.0, 1.0),
            b"ref-unrecognized": (0.0, 0.0, 1.0),
            b"photo": (0.0, 0.0, 1.0),
        },
    )
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({"k0": b"photo"}),
        encoder=encoder,
        min_score=0.1,
        min_margin=0.01,
    )
    result = classifier.classify("batch-1", (_file(0, "k0"),))
    assert isinstance(result, GroupingSuccess)
    assert all(
        group.group_id not in {UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID}
        for group in result.groups
    )


def test_permanent_failure_on_empty_pack(tmp_path: Path) -> None:
    pack = tmp_path / "empty"
    (pack / "reference").mkdir(parents=True)
    with pytest.raises(ValueError, match="reference"):
        OpenClipGroupClassifier(
            pack_dir=pack,
            storage=_StubStorage({}),
            encoder=_StubEncoder({}),
            min_score=0.5,
            min_margin=0.02,
        )


def test_build_open_clip_encoder_is_lazy_callable() -> None:
    from src.infrastructure.visit_photo_grouping import openclip_classifier as mod

    assert "open_clip" not in mod.__dict__
    assert "torch" not in mod.__dict__
    assert callable(mod.build_open_clip_encoder)


@dataclass(slots=True)
class _CountingEncoder:
    vectors: dict[bytes, tuple[float, ...]]
    calls: list[bytes] = field(default_factory=list)

    def encode(self, image_bytes: bytes) -> tuple[float, ...]:
        self.calls.append(image_bytes)
        try:
            return self.vectors[image_bytes]
        except KeyError as exc:
            raise RuntimeError(f"missing stub vector for {image_bytes!r}") from exc


def test_prototype_cache_skips_reference_encode_on_second_init(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    vectors = {
        b"ref-door": (1.0, 0.0),
        b"ref-display": (0.0, 1.0),
    }
    first = _CountingEncoder(vectors=vectors)
    OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=first,
        encoder_id="stub:v1",
        min_score=0.5,
        min_margin=0.02,
    )
    assert sorted(first.calls) == [b"ref-display", b"ref-door"]
    assert (pack / ".cache" / "openclip_reference_prototypes.v1.json").is_file()

    second = _CountingEncoder(vectors=vectors)
    OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=second,
        encoder_id="stub:v1",
        min_score=0.5,
        min_margin=0.02,
    )
    assert second.calls == []


def test_prototype_cache_invalidates_when_reference_bytes_change(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    vectors = {
        b"ref-door": (1.0, 0.0),
        b"ref-display": (0.0, 1.0),
        b"ref-door-changed": (0.9, 0.1),
    }
    OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=_CountingEncoder(vectors=vectors),
        encoder_id="stub:v1",
        min_score=0.5,
        min_margin=0.02,
    )
    (pack / "reference" / "door" / "door.jpg").write_bytes(b"ref-door-changed")
    encoder = _CountingEncoder(vectors=vectors)
    OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=encoder,
        encoder_id="stub:v1",
        min_score=0.5,
        min_margin=0.02,
    )
    assert b"ref-door-changed" in encoder.calls
    assert b"ref-display" in encoder.calls


def test_prototype_cache_invalidates_when_encoder_id_changes(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    vectors = {
        b"ref-door": (1.0, 0.0),
        b"ref-display": (0.0, 1.0),
    }
    OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=_CountingEncoder(vectors=vectors),
        encoder_id="stub:v1",
        min_score=0.5,
        min_margin=0.02,
    )
    encoder = _CountingEncoder(vectors=vectors)
    OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({}),
        encoder=encoder,
        encoder_id="stub:v2",
        min_score=0.5,
        min_margin=0.02,
    )
    assert sorted(encoder.calls) == [b"ref-display", b"ref-door"]


def test_classifier_reloads_new_learned_without_full_reencode(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    vectors = {
        b"ref-door": (1.0, 0.0),
        b"ref-display": (0.0, 1.0),
        b"learned-door": (0.95, 0.05),
        b"photo-learned": (0.94, 0.06),
    }
    encoder = _CountingEncoder(vectors=vectors)
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({"k0": b"photo-learned"}),
        encoder=encoder,
        min_score=0.5,
        min_margin=0.02,
        use_prototype_cache=False,
    )
    assert sorted(encoder.calls) == [b"ref-display", b"ref-door"]
    init_score = classifier.min_score
    init_margin = classifier.min_margin
    encoder.calls.clear()

    (pack / "reference" / "door" / "learned-batch-1-0.jpg").write_bytes(b"learned-door")
    result = classifier.classify("batch-1", (_file(0, "k0"),))
    assert isinstance(result, GroupingSuccess)
    assert encoder.calls == [b"learned-door", b"photo-learned"]
    assert classifier.min_score == init_score
    assert classifier.min_margin == init_margin
    by_id = {group.group_id: group.indexes for group in result.groups}
    assert by_id == {"door": (0,)}


def test_classifier_reload_noop_when_pack_unchanged(tmp_path: Path) -> None:
    pack = _pack_two_groups(tmp_path)
    vectors = {
        b"ref-door": (1.0, 0.0),
        b"ref-display": (0.0, 1.0),
        b"photo-door": (0.99, 0.01),
    }
    encoder = _CountingEncoder(vectors=vectors)
    classifier = OpenClipGroupClassifier(
        pack_dir=pack,
        storage=_StubStorage({"k0": b"photo-door"}),
        encoder=encoder,
        min_score=0.5,
        min_margin=0.02,
        use_prototype_cache=False,
    )
    encoder.calls.clear()
    first = classifier.classify("batch-1", (_file(0, "k0"),))
    second = classifier.classify("batch-1", (_file(0, "k0"),))
    assert isinstance(first, GroupingSuccess)
    assert isinstance(second, GroupingSuccess)
    assert encoder.calls == [b"photo-door", b"photo-door"]
