#!/usr/bin/env python3
import os
import sqlite3
import secrets
import hashlib
import time

DB_PATH = os.environ.get("ARC_LICENSE_DB", os.path.join(os.path.dirname(__file__), "license_core.db"))


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _now():
    return int(time.time())


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    if not salt_hex:
        salt_hex = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode(), bytes.fromhex(salt_hex), 120_000)
    return salt_hex, dk.hex()


def _mk_session() -> str:
    return secrets.token_urlsafe(32)


def init_db():
    c = _conn()
    try:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant TEXT NOT NULL,
              username TEXT NOT NULL,
              pass_salt TEXT NOT NULL,
              pass_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'user',
              created_at INTEGER NOT NULL,
              UNIQUE(tenant, username)
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
              token TEXT PRIMARY KEY,
              tenant TEXT NOT NULL,
              user_id INTEGER NOT NULL,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS license_keys (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant TEXT NOT NULL,
              license_key TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'new',
              bound_device TEXT DEFAULT '',
              bound_user TEXT DEFAULT '',
              bound_ip TEXT DEFAULT '',
              created_by TEXT DEFAULT 'admin',
              created_at INTEGER NOT NULL,
              activated_at INTEGER,
              note TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS license_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              license_key TEXT NOT NULL,
              tenant TEXT NOT NULL,
              event_type TEXT NOT NULL,
              actor TEXT DEFAULT '',
              ip TEXT DEFAULT '',
              user_agent TEXT DEFAULT '',
              details TEXT DEFAULT '',
              ts INTEGER NOT NULL
            );
            """
        )
        # schema migrations (safe on existing DB)
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(license_keys)").fetchall()]
            if "bound_ip" not in cols:
                c.execute("ALTER TABLE license_keys ADD COLUMN bound_ip TEXT DEFAULT ''")
        except Exception:
            pass
        c.commit()
    finally:
        c.close()


def register_user(tenant: str, username: str, password: str):
    tenant = (tenant or "DEMAN").strip().upper()
    username = (username or "").strip().lower()
    if len(username) < 3:
        return False, "username too short"
    if len(password or "") < 6:
        return False, "password too short"
    salt, h = _hash_password(password)
    c = _conn()
    try:
        c.execute(
            "INSERT INTO users (tenant, username, pass_salt, pass_hash, created_at) VALUES (?,?,?,?,?)",
            (tenant, username, salt, h, _now()),
        )
        c.commit()
        return True, "ok"
    except sqlite3.IntegrityError:
        return False, "username already exists"
    finally:
        c.close()


def login_user(tenant: str, username: str, password: str):
    tenant = (tenant or "DEMAN").strip().upper()
    username = (username or "").strip().lower()
    c = _conn()
    try:
        u = c.execute("SELECT * FROM users WHERE tenant=? AND username=?", (tenant, username)).fetchone()
        if not u:
            return False, "invalid credentials", None
        _, hh = _hash_password(password, u["pass_salt"])
        if hh != u["pass_hash"]:
            return False, "invalid credentials", None
        tok = _mk_session()
        exp = _now() + 60 * 60 * 24 * 30
        c.execute("INSERT INTO user_sessions (token, tenant, user_id, created_at, expires_at) VALUES (?,?,?,?,?)", (tok, tenant, int(u["id"]), _now(), exp))
        c.commit()
        return True, "ok", {"token": tok, "username": username, "user_id": int(u["id"]), "role": u["role"]}
    finally:
        c.close()


def get_session(tenant: str, token: str):
    tenant = (tenant or "DEMAN").strip().upper()
    token = (token or "").strip()
    if not token:
        return None
    c = _conn()
    try:
        row = c.execute(
            "SELECT s.*, u.username, u.role FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.tenant=?",
            (token, tenant),
        ).fetchone()
        if not row:
            return None
        if int(row["expires_at"] or 0) < _now():
            c.execute("DELETE FROM user_sessions WHERE token=?", (token,))
            c.commit()
            return None
        return {"user_id": int(row["user_id"]), "username": row["username"], "role": row["role"], "token": token}
    finally:
        c.close()


def logout_session(token: str):
    token = (token or "").strip()
    if not token:
        return
    c = _conn()
    try:
        c.execute("DELETE FROM user_sessions WHERE token=?", (token,))
        # schema migrations (safe on existing DB)
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(license_keys)").fetchall()]
            if "bound_ip" not in cols:
                c.execute("ALTER TABLE license_keys ADD COLUMN bound_ip TEXT DEFAULT ''")
        except Exception:
            pass
        c.commit()
    finally:
        c.close()


def _mk_key():
    raw = secrets.token_urlsafe(28).replace("_", "A").replace("-", "B")
    raw = ''.join(ch for ch in raw if ch.isalnum())[:36]
    return '-'.join([raw[i:i+6] for i in range(0, 36, 6)])


def create_keys(tenant: str, count: int, actor: str = "admin"):
    tenant = (tenant or "DEMAN").strip().upper()
    count = max(1, min(500, int(count)))
    ts = _now()
    out = []
    c = _conn()
    try:
        for _ in range(count):
            k = _mk_key()
            c.execute(
                "INSERT INTO license_keys (tenant, license_key, status, created_by, created_at) VALUES (?,?,?,?,?)",
                (tenant, k, "new", actor, ts),
            )
            c.execute(
                "INSERT INTO license_events (license_key, tenant, event_type, actor, ts) VALUES (?,?,?,?,?)",
                (k, tenant, "created", actor, ts),
            )
            out.append(k)
        c.commit()
        return out
    finally:
        c.close()


def _ua_sig(ua: str) -> str:
    return ' '.join(str(ua or '').lower().split())[:180]


def activate_license(tenant: str, license_key: str, device_id: str, user_id: str, actor_ip: str = "", user_agent: str = ""):
    tenant = (tenant or "DEMAN").strip().upper()
    k = (license_key or "").strip()
    d = (device_id or "").strip()
    u = (user_id or "").strip()
    if not k or not d:
        return False, "missing license/device"

    ts = _now()
    c = _conn()
    try:
        row = c.execute("SELECT * FROM license_keys WHERE license_key=? AND tenant=?", (k, tenant)).fetchone()
        if not row:
            return False, "license not found"
        if row["status"] in ("blocked", "revoked"):
            return False, "license blocked"
        if row["bound_device"] and row["bound_device"] != d:
            # Self-heal for same client after webview/browser storage resets.
            ev = c.execute(
                "SELECT ip, user_agent FROM license_events WHERE license_key=? AND tenant=? AND event_type IN ('activated','auto_rebind_same_client','admin_rebind_device') ORDER BY id DESC LIMIT 1",
                (k, tenant),
            ).fetchone()
            last_ip = (ev["ip"] or "").strip() if ev else ""
            last_ua = _ua_sig((ev["user_agent"] or "") if ev else "")
            cur_ua = _ua_sig(user_agent)
            if actor_ip and last_ip and actor_ip.strip() == last_ip and cur_ua and cur_ua == last_ua:
                c.execute("UPDATE license_keys SET bound_device=?, activated_at=COALESCE(activated_at, ?) WHERE id=?", (d, ts, row["id"]))
                c.execute(
                    "INSERT INTO license_events (license_key, tenant, event_type, actor, ip, user_agent, ts, details) VALUES (?,?,?,?,?,?,?,?)",
                    (k, tenant, "auto_rebind_same_client", u or "user", actor_ip, (user_agent or "")[:250], ts, "device-id changed; same ip+ua"),
                )
            else:
                return False, "license already bound to another device"
        if row["bound_user"] and u and row["bound_user"] != u:
            return False, "license already bound to another account"

        c.execute(
            "UPDATE license_keys SET status='active', bound_device=?, bound_user=COALESCE(NULLIF(?,''), bound_user), activated_at=COALESCE(activated_at, ?) WHERE id=?",
            (d, u, ts, row["id"]),
        )
        c.execute(
            "INSERT INTO license_events (license_key, tenant, event_type, actor, ip, user_agent, ts) VALUES (?,?,?,?,?,?,?)",
            (k, tenant, "activated", u or "user", actor_ip, (user_agent or "")[:250], ts),
        )
        c.commit()
        return True, "ok"
    finally:
        c.close()


def validate_license(tenant: str, license_key: str, device_id: str, user_id: str = ""):
    tenant = (tenant or "DEMAN").strip().upper()
    k = (license_key or "").strip()
    d = (device_id or "").strip()
    u = (user_id or "").strip()
    c = _conn()
    try:
        row = c.execute("SELECT * FROM license_keys WHERE license_key=? AND tenant=?", (k, tenant)).fetchone()
        if not row:
            return False, "license not found"
        if row["status"] in ("blocked", "revoked"):
            return False, "license blocked"
        if row["bound_device"] and row["bound_device"] != d:
            return False, "device mismatch"
        if row["bound_user"] and u and row["bound_user"] != u:
            return False, "user mismatch"
        return True, "ok"
    finally:
        c.close()


def admin_rebind_device(tenant: str, license_key: str, new_device: str, actor: str = "system"):
    tenant = (tenant or "DEMAN").strip().upper()
    k = (license_key or "").strip()
    d = (new_device or "").strip()
    if not k or not d:
        return False, "missing license/device"
    c = _conn()
    try:
        row = c.execute("SELECT * FROM license_keys WHERE tenant=? AND license_key=?", (tenant, k)).fetchone()
        if not row:
            return False, "license not found"
        if row["status"] in ("blocked", "revoked"):
            return False, "license blocked"
        old = (row["bound_device"] or "").strip()
        c.execute(
            "UPDATE license_keys SET status=CASE WHEN status='new' THEN 'active' ELSE status END, bound_device=?, activated_at=COALESCE(activated_at, ?) WHERE id=?",
            (d, _now(), int(row['id'])),
        )
        c.execute(
            "INSERT INTO license_events (license_key, tenant, event_type, actor, ts, details) VALUES (?,?,?,?,?,?)",
            (k, tenant, "admin_rebind_device", actor, _now(), f"{old[:16]} -> {d[:16]}"),
        )
        c.commit()
        return True, "rebound"
    finally:
        c.close()


if __name__ == "__main__":
    init_db()
    print(f"license db ready: {DB_PATH}")


