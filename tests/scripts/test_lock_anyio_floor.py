import re
from pathlib import Path

_LOCK = Path(__file__).resolve().parents[2] / "uv.lock"
_ANYIO_PACKAGE_VERSION = re.compile(
    r'name = "anyio"\nversion = "(\d+)\.(\d+)\.(\d+)"',
)


def _anyio_package_versions(text: str) -> list[tuple[int, int, int]]:
    return [
        (int(major), int(minor), int(patch))
        for major, minor, patch in _ANYIO_PACKAGE_VERSION.findall(text)
    ]


def test_lock_anyio_at_least_4_14_2() -> None:
    text = _LOCK.read_text(encoding="utf-8")
    versions = _anyio_package_versions(text)
    assert versions
    assert all(version >= (4, 14, 2) for version in versions)


def test_lock_anyio_versions_include_all_package_stanzas() -> None:
    sample = (
        '[[package]]\nname = "anyio"\nversion = "4.14.2"\n\n'
        '[[package]]\nname = "anyio"\nversion = "4.13.0"\n'
    )
    versions = _anyio_package_versions(sample)
    assert versions == [(4, 14, 2), (4, 13, 0)]
    assert not all(version >= (4, 14, 2) for version in versions)
