from __future__ import annotations

import os

import dotenv
import dotenv.main

# Tests must stay isolated from a developer's local .env.dev. Some third-party libraries
# (e.g. moy_sklad_api) call dotenv.load_dotenv() at import time, which would dump the real
# .env.dev into os.environ and leak into pydantic Settings (env_file=None alone cannot prevent
# this, since pydantic still reads os.environ). Neutralize load_dotenv before any test module
# imports those libraries, and signal our settings to skip the .env.dev file entirely.
os.environ.setdefault("MK_SERVICE_BOT_DISABLE_DOTENV", "1")
os.environ.setdefault("BOT_TOKEN", "test-bot-token")


def _noop_load_dotenv(*_args: object, **_kwargs: object) -> bool:
    return False


dotenv.load_dotenv = _noop_load_dotenv
dotenv.main.load_dotenv = _noop_load_dotenv
