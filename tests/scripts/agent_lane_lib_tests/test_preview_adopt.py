from __future__ import annotations

from pathlib import Path

from scripts.agent_lane_lib.dirty_gate import list_gated_dirty
from scripts.agent_lane_lib.preview_adopt import adopt_preview_paths


def test_adopt_copies_allowlist_into_lane_and_clears_primary(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    lane = tmp_path / "lane"
    primary.mkdir()
    lane.mkdir()
    demo = "docs/ui-demos/2026-10-09-x/index.html"
    adr = "docs/ui-adr/0018-foo.md"
    readme = "docs/ui-adr/README.md"
    for rel, body in (
        (demo, b"<html/>"),
        (adr, b"# adr\n"),
        (readme, b"# index\n"),
    ):
        path = primary / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    adopted = adopt_preview_paths(
        primary,
        lane,
        dirty_paths=[demo, adr, readme],
        is_untracked=lambda _p: True,
        head_blob_reader=lambda _p: None,
    )

    assert set(adopted) == {demo, adr, readme}
    for rel, body in ((demo, b"<html/>"), (adr, b"# adr\n"), (readme, b"# index\n")):
        assert (lane / rel).read_bytes() == body
        assert not (primary / rel).exists()


def test_adopt_skips_env_and_secret_basenames(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    lane = tmp_path / "lane"
    primary.mkdir()
    lane.mkdir()
    secret = "docs/ui-adr/desktop_client_secret.json"
    env = "docs/ui-demos/.env.local"
    ok = "docs/ui-demos/x.html"
    for rel, body in ((secret, b"sekrit"), (env, b"X=1"), (ok, b"move")):
        path = primary / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    adopted = adopt_preview_paths(
        primary,
        lane,
        dirty_paths=[secret, env, ok],
        is_untracked=lambda _p: True,
        head_blob_reader=lambda _p: None,
    )

    assert adopted == [ok]
    assert (lane / ok).read_bytes() == b"move"
    assert not (primary / ok).exists()
    assert (primary / secret).read_bytes() == b"sekrit"
    assert (primary / env).read_bytes() == b"X=1"
    assert not (lane / secret).exists()
    assert not (lane / env).exists()


def test_adopt_leaves_path_outside_allowlist(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    lane = tmp_path / "lane"
    primary.mkdir()
    lane.mkdir()
    outside = "docs/specs/keep.md"
    inside = "docs/ui-demos/x.html"
    (primary / outside).parent.mkdir(parents=True)
    (primary / outside).write_bytes(b"keep")
    (primary / inside).parent.mkdir(parents=True)
    (primary / inside).write_bytes(b"move")

    adopted = adopt_preview_paths(
        primary,
        lane,
        dirty_paths=[outside, inside],
        is_untracked=lambda _p: True,
        head_blob_reader=lambda _p: None,
    )

    assert adopted == [inside]
    assert (lane / inside).read_bytes() == b"move"
    assert not (primary / inside).exists()
    assert (primary / outside).read_bytes() == b"keep"
    assert not (lane / outside).exists()


def test_adopt_skill_adr_and_skill_demos(tmp_path: Path) -> None:
    # self-check: skill-adr path is adopted
    primary = tmp_path / "primary"
    lane = tmp_path / "lane"
    primary.mkdir()
    lane.mkdir()
    record = "docs/skill-adr/0001-options.md"
    demo = "docs/skill-demos/options/message.md"
    outside = "docs/notes/keep.md"
    secret = "docs/skill-adr/desktop_client_secret.json"
    for rel, body in (
        (record, b"# skill\n"),
        (demo, b"hello\n"),
        (outside, b"keep"),
        (secret, b"sekrit"),
    ):
        path = primary / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    adopted = adopt_preview_paths(
        primary,
        lane,
        dirty_paths=[record, demo, outside, secret],
        is_untracked=lambda _p: True,
        head_blob_reader=lambda _p: None,
    )

    assert set(adopted) == {record, demo}
    assert (lane / record).read_bytes() == b"# skill\n"
    assert (lane / demo).read_bytes() == b"hello\n"
    assert not (primary / record).exists()
    assert not (primary / demo).exists()
    assert (primary / outside).read_bytes() == b"keep"
    assert not (lane / outside).exists()
    assert (primary / secret).read_bytes() == b"sekrit"
    assert not (lane / secret).exists()
    gated = list_gated_dirty(
        primary,
        dirty_paths=[record, demo, outside, secret],
    )
    assert record in gated
    assert demo in gated
    assert outside not in gated
    assert secret not in gated
