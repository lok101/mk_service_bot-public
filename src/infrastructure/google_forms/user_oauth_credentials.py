from __future__ import annotations

from typing import Any

from beartype import beartype

_FORMS_USER_OAUTH_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms.body",
)


@beartype
def load_forms_user_oauth_credentials(credentials_file: str) -> Any:
    """Load authorized-user credentials for Drive + Forms inventory template copy."""
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
        credentials_file,
        scopes=_FORMS_USER_OAUTH_SCOPES,
    )


@beartype
def optional_copy_folder_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None
