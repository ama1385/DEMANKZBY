import ctypes as C
from functools import cache
import os
from pathlib import Path
import secrets
import subprocess
import sys

if sys.platform == "win32":
    import winreg
else:
    winreg = None

from arcraiders.auth._token import request_access_token
from arcraiders.config import (
    AUDIENCE,
    CLIENT_ID,
    CLIENT_SECRET,
    STEAM_APP_ID,
    STEAM_DLL_NAME,
    TENANCY,
    USER_AGENT,
)

AUTH_TICKET_BUFFER_SIZE = 8192
SUBPROCESS_TOKEN_PREFIX = "__ARCRAIDERS_TOKEN__="


def discover_steam_dll_path() -> str:
    if winreg is None:
        raise RuntimeError("Steam authentication is only supported on Windows")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
        steam_path = Path(winreg.QueryValueEx(key, "SteamPath")[0])

    library_paths = [steam_path]
    library_vdf = steam_path / "steamapps" / "libraryfolders.vdf"
    if library_vdf.exists():
        for line in library_vdf.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split('"')
            if len(parts) >= 6 and parts[1].isdigit():
                library_paths.append(Path(parts[3].replace("\\\\", "\\")))

    for library_path in library_paths:
        manifest_path = library_path / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        game_path = library_path / "steamapps" / "common" / "Arc Raiders"
        dll_path = game_path / STEAM_DLL_NAME
        if manifest_path.exists() and dll_path.exists():
            return str(dll_path)

    raise FileNotFoundError("Could not locate ARC Raiders steam_api64.dll in any Steam library")


class LocalSteamAuth:
    def __init__(self, dll_path: str | None = None) -> None:
        self.dll_path = dll_path or discover_steam_dll_path()

    @cache
    def token(self) -> str:
        return self._authenticate()

    def _authenticate(self) -> str:
        return _run_local_steam_auth_subprocess(self.dll_path)


def _run_local_steam_auth_subprocess(dll_path: str) -> str:
    # The Steam DLL writes directly to the process console during init, so run
    # the local auth flow in a subprocess and only parse the tagged token line.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arcraiders.auth.local_steam",
            dll_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    token = _extract_subprocess_token(result.stdout)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Steam auth subprocess failed: {details}")
    if token is None:
        raise RuntimeError("Steam auth subprocess did not return a token")
    return token


def _extract_subprocess_token(stdout: str) -> str | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(SUBPROCESS_TOKEN_PREFIX):
            return line.removeprefix(SUBPROCESS_TOKEN_PREFIX)
    return None


def _run_local_steam_auth(dll_path: str) -> str:
    steam, user, ticket, auth_token = _get_steam_auth_token(dll_path)
    try:
        return _exchange_steam_ticket_for_token(auth_token)
    finally:
        steam.SteamAPI_ISteamUser_CancelAuthTicket(user, C.c_uint32(ticket))
        steam.SteamAPI_Shutdown()


def _get_steam_auth_token(dll_path: str) -> tuple:
    if sys.platform != "win32":
        raise RuntimeError("Steam authentication is only supported on Windows")
    os.environ["SteamAppId"] = STEAM_APP_ID
    os.environ["SteamGameId"] = STEAM_APP_ID

    steam = C.WinDLL(dll_path)
    steam.SteamAPI_Init.restype = C.c_bool
    steam.SteamAPI_Shutdown.restype = None
    steam.SteamAPI_SteamUser_v021.restype = C.c_void_p
    steam.SteamAPI_ISteamUser_GetAuthSessionTicket.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_int,
        C.POINTER(C.c_uint32),
        C.c_void_p,
    ]
    steam.SteamAPI_ISteamUser_GetAuthSessionTicket.restype = C.c_uint32
    steam.SteamAPI_ISteamUser_CancelAuthTicket.argtypes = [C.c_void_p, C.c_uint32]
    steam.SteamAPI_ISteamUser_CancelAuthTicket.restype = None

    steam.SteamAPI_Init()
    user = C.c_void_p(steam.SteamAPI_SteamUser_v021())
    buf = (C.c_ubyte * AUTH_TICKET_BUFFER_SIZE)()
    out_len = C.c_uint32(0)
    ticket = steam.SteamAPI_ISteamUser_GetAuthSessionTicket(
        user,
        C.byref(buf),
        len(buf),
        C.byref(out_len),
        C.c_void_p(0),
    )
    auth_token = bytes(buf[: out_len.value]).hex().upper()
    return steam, user, ticket, auth_token


def _exchange_steam_ticket_for_token(external_provider_token: str) -> str:
    form_data = {
        "grant_type": "client_credentials",
        "external_provider_name": "steam",
        "external_provider_token": external_provider_token,
        "audience": AUDIENCE,
        "app_id": STEAM_APP_ID,
        "tenancy": TENANCY,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    headers = {
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
        "x-embark-telemetry-uuid": secrets.token_hex(10),
        "x-embark-telemetry-client-platform": "3",
        "x-embark-request-id": secrets.token_hex(10),
        "Accept-Encoding": "gzip",
    }
    return request_access_token(
        form_data=form_data,
        headers=headers,
        error_prefix="Embark external token exchange failed",
    )


def _main() -> int:
    dll_path = sys.argv[1] if len(sys.argv) > 1 else discover_steam_dll_path()
    token = _run_local_steam_auth(dll_path)
    print(f"{SUBPROCESS_TOKEN_PREFIX}{token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
