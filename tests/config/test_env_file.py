from __future__ import annotations

from unittest.mock import patch

from src.config._base import default_env_file


def test_default_env_file_is_env_dev_when_not_under_pytest() -> None:
    with patch("src.config._base._running_under_pytest", return_value=False):
        assert default_env_file() == ".env.dev"


def test_default_env_file_is_none_under_pytest() -> None:
    with patch("src.config._base._running_under_pytest", return_value=True):
        assert default_env_file() is None
