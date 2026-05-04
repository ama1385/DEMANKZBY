import base64
from functools import cache
import hashlib
import os
import threading
import uuid
import webbrowser
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib import parse

from arcraiders.auth._token import request_access_token
from arcraiders.config import (
    AUDIENCE,
    AUTH_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    OAUTH_CALLBACK_URL,
    OAUTH_SCOPE,
    TENANCY,
    USER_AGENT,
)


class OAuthProvider(StrEnum):
    EPIC = "epic"
    PLAYSTATION = "playstation"
    STEAM = "steam"
    XBOX = "xbox"


class BrowserOAuth:
    def __init__(self, provider: OAuthProvider, redirect_uri: str = OAUTH_CALLBACK_URL) -> None:
        self.provider = provider
        self.redirect_uri = redirect_uri

    @cache
    def token(self) -> str:
        return self._authenticate()

    def _authenticate(self) -> str:
        state = uuid.uuid4().hex
        code_verifier, code_challenge = _create_pkce_pair()
        query = {
            "skip_link": "false",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "audience": AUDIENCE,
            "scope": OAUTH_SCOPE,
            "tenancy": TENANCY,
            "external_provider_name": self.provider.value,
        }
        authorize_url = f"{AUTH_URL}?{parse.urlencode(query)}"
        webbrowser.open(authorize_url)
        callback_data = _wait_for_oauth_callback(redirect_uri=self.redirect_uri, expected_state=state)
        return _exchange_authorization_code_for_token(
            code=callback_data["code"],
            code_verifier=code_verifier,
            redirect_uri=self.redirect_uri,
        )


def _base64url_no_padding(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _create_pkce_pair() -> tuple[str, str]:
    verifier = _base64url_no_padding(os.urandom(32))
    challenge = _base64url_no_padding(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _wait_for_oauth_callback(redirect_uri: str, expected_state: str, timeout_seconds: int = 180) -> dict[str, str]:
    parsed = parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    callback_data: dict[str, str] = {}
    done = threading.Event()

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_parsed = parse.urlparse(self.path)
            if request_parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return

            query = parse.parse_qs(request_parsed.query)
            callback_data["code"] = query.get("code", [""])[0]
            callback_data["state"] = query.get("state", [""])[0]
            callback_data["scope"] = query.get("scope", [""])[0]
            callback_data["error"] = query.get("error", [""])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Login complete. You can close this tab.")
            done.set()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    httpd = HTTPServer((host, port), OAuthCallbackHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        if not done.wait(timeout_seconds):
            raise TimeoutError("Timed out waiting for OAuth callback")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)

    if callback_data.get("error"):
        raise ValueError(f"OAuth authorization failed: {callback_data['error']}")
    if not callback_data.get("code"):
        raise ValueError("OAuth callback did not include a code")
    if callback_data.get("state") != expected_state:
        raise ValueError("OAuth state mismatch")
    return callback_data


def _exchange_authorization_code_for_token(code: str, code_verifier: str, redirect_uri: str) -> str:
    form_data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }
    return request_access_token(
        form_data=form_data,
        headers=headers,
        error_prefix="Embark authorization code exchange failed",
    )
