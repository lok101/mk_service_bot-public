from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from beartype import beartype


@beartype
def create_prefilled_google_form_url(
    form_url: str,
    entry_id: str,
    value: str,
) -> str:
    if not form_url:
        raise ValueError("Google Form URL must not be empty")
    if not entry_id.startswith("entry."):
        raise ValueError("Google Form entry id must start with 'entry.'")
    if not value:
        raise ValueError("Google Form prefilled value must not be empty")

    parts = urlsplit(form_url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params["usp"] = "pp_url"
    query_params[entry_id] = value

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_params),
            parts.fragment,
        ),
    )
