from __future__ import annotations

from pathlib import Path

from scripts.agent_lane_lib.overlap import classify_overlap


def test_classify_empty_intersection(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "only-primary.txt").write_bytes(b"x")
    blobs = {"lane-only.txt": b"y"}

    result = classify_overlap(
        primary,
        incoming_paths=["lane-only.txt"],
        lane_blob_reader=blobs.get,
        dirty_paths=["only-primary.txt"],
    )

    assert result == []


def test_classify_identical_untracked(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    rel = "docs/ui-demos/demo/index.html"
    path = primary / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"<html>same</html>")
    blobs = {rel: b"<html>same</html>"}

    result = classify_overlap(
        primary,
        incoming_paths=[rel],
        lane_blob_reader=blobs.get,
        dirty_paths=[rel],
    )

    assert result == [(rel, "identical")]


def test_classify_identical_tracked(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    rel = "docs/ui-adr/README.md"
    path = primary / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# index\n")
    blobs = {rel: b"# index\n"}

    result = classify_overlap(
        primary,
        incoming_paths=[rel, "other.md"],
        lane_blob_reader=blobs.get,
        dirty_paths=[rel],
    )

    assert result == [(rel, "identical")]


def test_classify_ignores_path_outside_incoming(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    outside = "docs/specs/other.md"
    (primary / outside).parent.mkdir(parents=True)
    (primary / outside).write_bytes(b"dirty")
    incoming = "docs/ui-demos/x.html"
    blobs = {incoming: b"lane", outside: b"dirty"}

    result = classify_overlap(
        primary,
        incoming_paths=[incoming],
        lane_blob_reader=blobs.get,
        dirty_paths=[outside],
    )

    assert result == []


def test_classify_differs(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    rel = "docs/ui-demos/demo/index.html"
    path = primary / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"primary-version")
    blobs = {rel: b"lane-version"}

    result = classify_overlap(
        primary,
        incoming_paths=[rel],
        lane_blob_reader=blobs.get,
        dirty_paths=[rel],
    )

    assert result == [(rel, "differs")]
