from __future__ import annotations

from pathlib import Path

from src.application.visit_photo_review.commands import (
    AppendLearnedReference,
    AppendLearnedReferenceError,
    WriteGroupAvatar,
    WriteGroupAvatarError,
)
from src.infrastructure.visit_photo_review.group_avatar import (
    PackDirGroupAvatarReader,
    PackDirGroupAvatarWriter,
    PackDirLearnedReferenceWriter,
)

_JPEG = b"\xff\xd8\xff" + b"jpeg-payload"
_JPEG_OTHER = b"\xff\xd8\xff" + b"other-jpeg"
_PNG = b"\x89PNG\r\n\x1a\n" + b"png-payload"


def test_group_avatar_reads_first_image(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "b.png").write_bytes(b"png-bytes")
    (group_dir / "a.jpg").write_bytes(b"jpg-bytes")
    reader = PackDirGroupAvatarReader(tmp_path)
    avatar = reader.read_avatar("waste_tank")
    assert avatar is not None
    assert avatar.content == b"jpg-bytes"
    assert avatar.content_type == "image/jpeg"


def test_group_avatar_prefers_avatar_file(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "a.jpg").write_bytes(b"jpg-bytes")
    (group_dir / "avatar.png").write_bytes(_PNG)
    (group_dir / "learned-batch-0.jpg").write_bytes(_JPEG)
    reader = PackDirGroupAvatarReader(tmp_path)
    avatar = reader.read_avatar("waste_tank")
    assert avatar is not None
    assert avatar.content == _PNG
    assert avatar.content_type == "image/png"


def test_group_avatar_falls_back_to_first_learned(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "learned-b-1.jpg").write_bytes(_JPEG_OTHER)
    (group_dir / "learned-a-0.jpg").write_bytes(_JPEG)
    reader = PackDirGroupAvatarReader(tmp_path)
    avatar = reader.read_avatar("waste_tank")
    assert avatar is not None
    assert avatar.content == _JPEG


def test_group_avatar_missing_returns_none(tmp_path: Path) -> None:
    reader = PackDirGroupAvatarReader(tmp_path)
    assert reader.read_avatar("waste_tank") is None


def test_group_avatar_none_pack_dir_returns_none() -> None:
    reader = PackDirGroupAvatarReader(None)
    assert reader.read_avatar("waste_tank") is None


def test_group_avatar_rejects_path_traversal(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "a.jpg").write_bytes(b"ok")
    (tmp_path / "secret.jpg").write_bytes(b"secret")
    reader = PackDirGroupAvatarReader(tmp_path)
    assert reader.read_avatar("../secret") is None
    assert reader.read_avatar("..\\secret") is None
    assert reader.read_avatar("waste_tank/../secret") is None
    assert reader.read_avatar("waste_tank\\..\\secret") is None
    assert reader.read_avatar("/etc/passwd") is None
    assert reader.read_avatar("waste_tank") is not None


def test_write_group_avatar_readable_by_pack_reader(tmp_path: Path) -> None:
    writer = PackDirGroupAvatarWriter(tmp_path)
    reader = PackDirGroupAvatarReader(tmp_path)
    result = WriteGroupAvatar(writer).execute(
        group_id="waste_tank",
        content=_JPEG,
        content_type="image/jpeg",
    )
    assert result.is_ok()
    avatar = reader.read_avatar("waste_tank")
    assert avatar is not None
    assert avatar.content == _JPEG
    assert avatar.content_type == "image/jpeg"


def test_write_group_avatar_replaces_existing_avatar_only(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "avatar.png").write_bytes(_PNG)
    (group_dir / "old.png").write_bytes(_PNG)
    writer = PackDirGroupAvatarWriter(tmp_path)
    reader = PackDirGroupAvatarReader(tmp_path)
    assert (
        WriteGroupAvatar(writer)
        .execute(
            group_id="waste_tank",
            content=_JPEG,
            content_type="image/jpeg",
        )
        .is_ok()
    )
    avatar = reader.read_avatar("waste_tank")
    assert avatar is not None
    assert avatar.content == _JPEG
    names = sorted(path.name for path in group_dir.iterdir())
    assert names == ["avatar.jpg", "old.png"]


def test_write_group_avatar_preserves_learned(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    learned = group_dir / "learned-batch-0.jpg"
    learned.write_bytes(_JPEG_OTHER)
    writer = PackDirGroupAvatarWriter(tmp_path)
    assert (
        WriteGroupAvatar(writer)
        .execute(
            group_id="waste_tank",
            content=_JPEG,
            content_type="image/jpeg",
        )
        .is_ok()
    )
    assert learned.read_bytes() == _JPEG_OTHER
    assert (group_dir / "avatar.jpg").read_bytes() == _JPEG


def test_write_group_avatar_rejects_path_traversal(tmp_path: Path) -> None:
    writer = PackDirGroupAvatarWriter(tmp_path)
    result = WriteGroupAvatar(writer).execute(
        group_id="../secret",
        content=_JPEG,
        content_type="image/jpeg",
    )
    assert result.is_err()
    assert result.error is WriteGroupAvatarError.UNSAFE_GROUP_ID
    assert not (tmp_path / "secret").exists()
    assert not (tmp_path / "reference" / "secret").exists()


def test_write_group_avatar_rejects_without_pack_dir() -> None:
    writer = PackDirGroupAvatarWriter(None)
    result = WriteGroupAvatar(writer).execute(
        group_id="waste_tank",
        content=_JPEG,
        content_type="image/jpeg",
    )
    assert result.is_err()
    assert result.error is WriteGroupAvatarError.PACK_DIR_UNAVAILABLE


def test_append_learned_writes_learned_file(tmp_path: Path) -> None:
    writer = PackDirLearnedReferenceWriter(tmp_path)
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=3,
        content=_JPEG,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_ok()
    target = tmp_path / "reference" / "waste_tank" / "learned-batch-1-3.jpg"
    assert target.read_bytes() == _JPEG
    assert not (tmp_path / "reference" / "waste_tank" / "avatar.jpg").exists()


def test_append_learned_skips_at_cap(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "learned-a-0.jpg").write_bytes(_JPEG)
    (group_dir / "learned-b-1.jpg").write_bytes(_JPEG_OTHER)
    writer = PackDirLearnedReferenceWriter(tmp_path)
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-2",
        index=0,
        content=b"\xff\xd8\xff" + b"third",
        content_type="image/jpeg",
        max_per_group=2,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.SKIP_CAP
    assert not (group_dir / "learned-batch-2-0.jpg").exists()


def test_append_learned_skips_duplicate_hash(tmp_path: Path) -> None:
    group_dir = tmp_path / "reference" / "waste_tank"
    group_dir.mkdir(parents=True)
    (group_dir / "avatar.jpg").write_bytes(_JPEG)
    writer = PackDirLearnedReferenceWriter(tmp_path)
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=0,
        content=_JPEG,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.SKIP_DUP
    assert list(group_dir.iterdir()) == [group_dir / "avatar.jpg"]


def test_append_learned_pack_unavailable() -> None:
    writer = PackDirLearnedReferenceWriter(None)
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=0,
        content=_JPEG,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.PACK_UNAVAILABLE


def test_append_learned_rejects_unsafe_group_id(tmp_path: Path) -> None:
    writer = PackDirLearnedReferenceWriter(tmp_path)
    result = AppendLearnedReference(writer).execute(
        group_id="../secret",
        batch_id="batch-1",
        index=0,
        content=_JPEG,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.INVALID
    assert not (tmp_path / "secret").exists()
