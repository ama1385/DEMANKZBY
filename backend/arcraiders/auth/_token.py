import json
from urllib import error
from urllib import parse, request

from arcraiders.config import TOKEN_URL


def request_access_token(
    form_data: dict[str, str],
    headers: dict[str, str],
    error_prefix: str,
) -> str:
    payload = parse.urlencode(form_data).encode("utf-8")
    req = request.Request(
        url=TOKEN_URL,
        data=payload,
        method="POST",
        headers=headers,
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{error_prefix}: HTTP {exc.code} {body}") from exc

    token_data = json.loads(body)
    return str(token_data["access_token"])
