#!/usr/bin/env python3
import os
import time
import json
import requests
import sqlite3
import csv
import re
from datetime import datetime
from license_core import init_db, create_keys, admin_reset_license, admin_revoke_license, admin_revoke_many

def _dec_secret(v: str) -> str:
    s = (v or "").strip()
    if not s.lower().startswith("enc::"):
        return s
    token = s.split("::", 1)[1].strip()
    key = (os.environ.get("TOKEN_MASTER_KEY") or "").strip()
    key_file = (os.environ.get("TOKEN_MASTER_KEY_FILE") or "/home/kabny/.openclaw/workspace/runtime/.token_master.key").strip()
    try:
        if not key:
            with open(key_file, "rb") as f:
                key = f.read().strip().decode("utf-8")
        from cryptography.fernet import Fernet
        return Fernet(key.encode("utf-8")).decrypt(token.encode("utf-8")).decode("utf-8").strip()
    except Exception:
        return ""

BOT_TOKEN = _dec_secret(os.environ.get("TG_BOT_TOKEN", ""))
OWNER_ID = str(os.environ.get("TG_OWNER_ID", "")).strip()
TENANT = (os.environ.get("TG_TENANT", "DEMAN.STORE") or "DEMAN.STORE").strip().upper()
STATE_FILE = os.environ.get("TG_STATE_FILE", os.path.join(os.path.dirname(__file__), f"tg_state_{TENANT}.json"))
NOTES_FILE = os.environ.get("TG_NOTES_FILE", os.path.join(os.path.dirname(__file__), f"tg_notes_{TENANT}.json"))
HARD_DENY_IDS = {x.strip() for x in (os.environ.get("TG_HARD_DENY_IDS") or "").split(",") if x.strip()}
APPROVER_IDS = {x.strip() for x in (os.environ.get("TG_APPROVER_IDS") or "").split(",") if x.strip()}
APPROVER_IDS.add(OWNER_ID)
ENABLE_DAYKEY = (os.environ.get("TG_ENABLE_DAYKEY", "0") or "").strip().lower() in ("1", "true", "yes", "on")
ALLOW_HARD_DELETE = (os.environ.get("TG_ALLOW_HARD_DELETE", "0") or "").strip().lower() in ("1", "true", "yes", "on")

if not BOT_TOKEN or not OWNER_ID:
    raise SystemExit("Missing TG_BOT_TOKEN or TG_OWNER_ID")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

BOT_COMMANDS = [
    {"command": "start", "description": "فتح لوحة التحكم"},
    {"command": "key", "description": "توليد مفتاح جديد (سيطلب يوزر العميل)"},
    {"command": "daykey", "description": "مفتاح يوم واحد: /daykey أو /daykey 5"},
    {"command": "resetkey", "description": "ريست مفتاح: /resetkey KEY [@username]"},
    {"command": "delkey", "description": "حذف/إلغاء كي: /delkey KEY"},
    {"command": "delkeys", "description": "حذف مجموعة: /delkeys K1,K2"},
    {"command": "purge_revoked", "description": "حذف revoked محدد: /purge_revoked K1,K2"},
    {"command": "stock", "description": "جرد الكيات + المنشئ + النوت"},
    {"command": "alerts", "description": "آخر محاولات الكراك/IP"},
    {"command": "find", "description": "بحث بكي/نوت: /find text"},
    {"command": "finduser", "description": "بحث بمفاتيح العميل: /finduser @username"},
    {"command": "stockcsv", "description": "تصدير كل الكيات Excel CSV"},
    {"command": "pending", "description": "طلبات الموافقة المعلقة (للمالك)"},
    {"command": "note", "description": "إضافة نوت: /note KEY النص"},
]

MENU_KB = {
    "keyboard": [
        [{"text": "🔑 مفتاح جديد"}, {"text": "🔑 5 مفاتيح"}],
        [{"text": "⏰ كي يوم واحد"}, {"text": "♻️ ريست مفتاح"}],
        [{"text": "🗑️ حذف كي"}, {"text": "🗑️ حذف مجموعة"}],
        [{"text": "🧹 حذف revoked محدد"}],
        [{"text": "📦 جرد الكيات"}, {"text": "📊 اكسل الكيات"}],
        [{"text": "🔎 بحث كي"}, {"text": "👤 بحث عميل"}],
        [{"text": "🚨 محاولات كراك"}],
        [{"text": "📋 الأوامر"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
            if "approved" not in s:
                s["approved"] = [OWNER_ID]
            # Always auto-approve owner + approvers from env
            for _aid in APPROVER_IDS:
                if _aid and _aid not in s["approved"]:
                    s["approved"].append(_aid)
            if "pending" not in s:
                s["pending"] = {}
            if "offset" not in s:
                s["offset"] = 0
            if "reset_wait" not in s:
                s["reset_wait"] = {}
            if "key_wait" not in s:
                s["key_wait"] = {}
            if "note_wait" not in s:
                s["note_wait"] = {}
            if "del_wait" not in s:
                s["del_wait"] = {}
            if "find_wait" not in s:
                s["find_wait"] = {}
            if "find_user_wait" not in s:
                s["find_user_wait"] = {}
            if "purge_wait" not in s:
                s["purge_wait"] = {}
            return s
    except Exception:
        return {"approved": sorted([x for x in APPROVER_IDS if x]), "pending": {}, "offset": 0, "reset_wait": {}, "key_wait": {}, "note_wait": {}, "del_wait": {}, "find_wait": {}, "find_user_wait": {}, "purge_wait": {}}

def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def send(chat_id, text, keyboard=False, markdown=False):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = MENU_KB
    if markdown:
        payload["parse_mode"] = "Markdown"
    requests.post(f"{API}/sendMessage", json=payload, timeout=20)

def send_document(chat_id, file_path, caption=""):
    try:
        with open(file_path, "rb") as f:
            requests.post(
                f"{API}/sendDocument",
                data={"chat_id": chat_id, "caption": caption or ""},
                files={"document": f},
                timeout=60,
            )
    except Exception:
        pass


def send_key(chat_id, key):
    # one key per message to make copy easy on mobile + note button per key
    requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": f"`{key}`",
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "📝 ضيف نوت", "callback_data": f"note:{key}"},
                    {"text": "📖 اظهار النوت", "callback_data": f"shownote:{key}"}
                ]]
            },
        },
        timeout=20,
    )

def owner_notify_approval(user_id):
    requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": OWNER_ID,
            "text": f"طلب دخول جديد: {user_id}",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "✅ موافقة", "callback_data": f"approve:{user_id}"}
                ]]
            },
        },
        timeout=20,
    )


def owner_notify_denied(user_id):
    send(OWNER_ID, f"🚫 محاولة مرفوضة تلقائيًا\nuser: {user_id}\ntenant: {TENANT}", keyboard=True)


def notify_all_pending(st):
    p = st.get("pending") or {}
    if not p:
        send(OWNER_ID, "لا يوجد طلبات موافقة معلقة ✅", keyboard=True)
        return
    for uid in list(p.keys()):
        owner_notify_approval(uid)


def load_notes():
    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_notes(d):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def add_note(license_key: str, by_user: str, note_text: str):
    d = load_notes()
    arr = d.get(license_key) or []
    arr.append({"by": str(by_user), "note": str(note_text), "ts": int(time.time())})
    d[license_key] = arr
    save_notes(d)


def _normalize_username(raw: str) -> str:
    s = str(raw or "").strip().lower().replace(" ", "")
    s = s.lstrip("@")
    if not s:
        return ""
    if not re.fullmatch(r"[a-z0-9_\.]{3,64}", s):
        return ""
    return s


def _client_note_marker(username: str, action: str = "") -> str:
    u = _normalize_username(username)
    if not u:
        return ""
    a = str(action or "").strip().lower()
    if a:
        return f"client:@{u} | action:{a}"
    return f"client:@{u}"


def _extract_username_from_note(note_text: str) -> str:
    s = str(note_text or "")
    m = re.search(r"client\s*:\s*@?([a-zA-Z0-9_\.]{3,64})", s, flags=re.I)
    if m:
        return _normalize_username(m.group(1))
    m2 = re.search(r"\B@([a-zA-Z0-9_\.]{3,64})\b", s)
    if m2:
        return _normalize_username(m2.group(1))
    return ""


def _extract_action_from_note(note_text: str) -> str:
    s = str(note_text or "")
    m = re.search(r"action\s*:\s*([a-zA-Z0-9_\-]{2,32})", s, flags=re.I)
    if not m:
        return ""
    return str(m.group(1) or "").strip().lower()


def _key_row_map(limit: int = 50000):
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT license_key, status, created_by, created_at FROM license_keys WHERE tenant=? ORDER BY created_at DESC LIMIT ?",
            (TENANT, max(1000, min(200000, int(limit or 50000)))),
        ).fetchall()
        return {str(r["license_key"] or ""): r for r in rows}
    finally:
        conn.close()


def _find_keys_for_username(username: str):
    u = _normalize_username(username)
    if not u:
        return []
    notes = load_notes()
    key_rows = _key_row_map()
    out = []
    for key, arr in (notes or {}).items():
        key = str(key or "").strip()
        if not key:
            continue
        hit = False
        for it in (arr or []):
            if _extract_username_from_note(it.get("note", "")) == u:
                hit = True
                break
        if not hit:
            continue
        r = key_rows.get(key)
        if not r:
            continue
        out.append({
            "license_key": key,
            "status": str(r["status"] or "").lower(),
            "created_at": int(r["created_at"] or 0),
        })
    out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return out


def _client_usage_stats(username: str):
    u = _normalize_username(username)
    stats = {
        "username": u,
        "key_requests": 0,
        "reset_requests": 0,
        "active_keys": [],
        "new_keys": [],
        "linked_keys": [],
    }
    if not u:
        return stats

    notes = load_notes()
    key_rows = _key_row_map()
    linked = set()

    for key, arr in (notes or {}).items():
        k = str(key or "").strip()
        if not k:
            continue
        hit_this_key = False
        for it in (arr or []):
            note = str((it or {}).get("note", ""))
            if _extract_username_from_note(note) != u:
                continue
            hit_this_key = True
            act = _extract_action_from_note(note)
            if act in ("reset", "resetkey"):
                stats["reset_requests"] += 1
            elif act in ("key", "keygen", "newkey", "create"):
                stats["key_requests"] += 1
            else:
                # legacy markers without action are treated as key-requests
                stats["key_requests"] += 1

        if not hit_this_key:
            continue

        linked.add(k)
        r = key_rows.get(k)
        if not r:
            continue
        st = str(r["status"] or "").lower()
        if st == "active":
            stats["active_keys"].append(k)
        elif st == "new":
            stats["new_keys"].append(k)

    stats["linked_keys"] = sorted(linked)
    return stats


def _format_client_usage(username: str) -> str:
    s = _client_usage_stats(username)
    u = s.get("username") or _normalize_username(username)
    lines = [f"📊 إحصائيات العميل @{u}"]
    lines.append(f"• عدد مرات طلب مفتاح جديد: {int(s.get('key_requests') or 0)}")
    lines.append(f"• عدد مرات الريست: {int(s.get('reset_requests') or 0)}")
    lines.append(f"• عدد المفاتيح المرتبطة: {len(s.get('linked_keys') or [])}")
    active = s.get("active_keys") or []
    lines.append(f"• مفاتيح Active حاليًا: {len(active)}")
    if active:
        for k in active[:5]:
            lines.append(f"  - `{k}`")
    return "\n".join(lines)


def _active_keys_for_username(username: str):
    s = _client_usage_stats(username)
    return list(s.get("active_keys") or [])


def _format_user_keys_by_username(username: str) -> str:
    u = _normalize_username(username)
    rows = _find_keys_for_username(u)
    if not u:
        return "❌ اليوزر غير صحيح"
    if not rows:
        return f"لا يوجد مفاتيح مرتبطة بالعميل @{u}"
    lines = [f"🔎 مفاتيح العميل @{u} ({len(rows)})"]
    for r in rows[:20]:
        lines.append(f"• `{r.get('license_key','')}` ({_status_ar(r.get('status',''))})")
    if len(rows) > 20:
        lines.append(f"… و {len(rows)-20} إضافي")
    return "\n".join(lines)


def _status_ar(st: str) -> str:
    s = str(st or "").lower()
    return {
        "active": "فعال",
        "new": "جديد",
        "revoked": "ملغي",
        "expired": "منتهي",
    }.get(s, s or "-")


def _client_blocking_keys(username: str, ignore_key: str = ""):
    ig = str(ignore_key or "").strip()
    rows = _find_keys_for_username(username)
    blocked = []
    for r in rows:
        k = str(r.get("license_key") or "")
        st = str(r.get("status") or "").lower()
        if ig and k == ig:
            continue
        if st in ("new", "active"):
            blocked.append(r)
    return blocked


def _format_client_exists_warning(username: str, rows):
    u = _normalize_username(username)
    lines = [f"⚠️ تنبيه: العميل @{u} عنده مفتاح مسبقًا:"]
    for r in rows[:5]:
        lines.append(f"• `{r.get('license_key','')}` ({_status_ar(r.get('status',''))})")
    lines.append("ℹ️ تنبيه فقط — سيتم تنفيذ طلبك وتسجيل ذلك في النوت.")
    return "\n".join(lines)


def _ask_username(chat_id, action_label: str):
    send(chat_id, f"ارسل يوزر العميل الآن (مثال: @username)\nالإجراء: {action_label}", keyboard=True)


def get_notes_text(license_key: str):
    d = load_notes()
    arr = d.get(license_key) or []
    if not arr:
        return "لا توجد نوتات لهذا الكي"
    lines = [f"🗒️ نوتات الكي:\n`{license_key}`"]
    for i, it in enumerate(arr[-10:], 1):
        lines.append(f"{i}) {it.get('note','')} (by {it.get('by','-')})")
    return "\n".join(lines)


def _db_path():
    return (os.environ.get("ARC_LICENSE_DB") or os.path.join(os.path.dirname(__file__), "license_core.db")).strip()


def _alerts_path():
    return os.path.join(os.path.dirname(__file__), f"ip_guard_alerts_{TENANT}.log")


def get_alerts_text(limit: int = 20):
    p = _alerts_path()
    if not os.path.isfile(p):
        return "لا توجد محاولات كراك مسجلة حتى الآن ✅"
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = [x.strip() for x in f.readlines() if x.strip()]
    except Exception:
        return "تعذر قراءة ملف التنبيهات"
    if not lines:
        return "لا توجد محاولات كراك مسجلة حتى الآن ✅"
    rows = lines[-max(1, min(100, int(limit or 20))):]
    out = [f"🚨 آخر {len(rows)} محاولة ({TENANT})"]
    for ln in rows:
        parts = dict(item.split("=", 1) for item in ln.split("\t") if "=" in item)
        ts = ln.split("\t", 1)[0]
        try:
            t = datetime.fromtimestamp(int(ts)).strftime('%m-%d %H:%M')
        except Exception:
            t = ts
        ip = parts.get("ip", "-")
        reason = parts.get("reason", "-")
        out.append(f"• {t} | {ip} | {reason}")
    return "\n".join(out)


def _md_escape(v: str) -> str:
    s = str(v or "")
    for ch in "_*[]()~`>#+-=|{}.!":
        s = s.replace(ch, "\\" + ch)
    return s


def _rows_to_chunks(rows, title: str):
    if not rows:
        return [("لا توجد نتائج.", False)]
    notes = load_notes()
    chunks = []
    cur_rows = []

    def _flush():
        if not cur_rows:
            return
        body = [title, "```", "#  KEY                              STATUS   BY         NOTE"]
        body.extend(cur_rows)
        body.append("```")
        chunks.append(("\n".join(body), True))

    for i, r in enumerate(rows, 1):
        key = str(r["license_key"] or "")
        status = str(r["status"] or "-")[:8]
        by = str(r["created_by"] or "-")[:10]
        arr = notes.get(key) or []
        note = (arr[-1].get("note", "") if arr else "-").replace("\n", " ").strip()
        if len(note) > 26:
            note = note[:26] + "…"
        row_txt = f"{str(i).rjust(2)} {key:<32} {status:<8} {by:<10} {note}"
        if len(cur_rows) >= 40:
            _flush()
            cur_rows = []
        cur_rows.append(row_txt)
    _flush()
    return chunks


def get_key_inventory_text(limit: int = 5000):
    limit = max(1, min(50000, int(limit or 5000)))
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT license_key, status, created_by, created_at FROM license_keys WHERE tenant=? ORDER BY created_at DESC LIMIT ?",
            (TENANT, limit),
        ).fetchall()
    finally:
        conn.close()
    return _rows_to_chunks(rows, f"📦 جرد الكيات ({TENANT}) — {len(rows)}")


def export_stock_csv() -> str:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    notes = load_notes()
    out_path = os.path.join(os.path.dirname(__file__), f"stock_{TENANT}.csv")
    try:
        rows = conn.execute(
            "SELECT license_key, status, created_by, created_at, activated_at FROM license_keys WHERE tenant=? ORDER BY created_at DESC",
            (TENANT,),
        ).fetchall()
    finally:
        conn.close()

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["license_key", "status", "created_by", "created_at", "activated_at", "last_note"])
        for r in rows:
            key = str(r["license_key"] or "")
            arr = notes.get(key) or []
            note = (arr[-1].get("note", "") if arr else "")
            w.writerow([
                key,
                r["status"] or "",
                r["created_by"] or "",
                r["created_at"] or "",
                r["activated_at"] or "",
                note,
            ])
    return out_path


def find_keys_text(query: str, limit: int = 500):
    q = (query or "").strip().lower()
    if not q:
        return [("استخدم: /find كلمة_بحث", False)]
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT license_key, status, created_by, created_at FROM license_keys WHERE tenant=? ORDER BY created_at DESC LIMIT 50000",
            (TENANT,),
        ).fetchall()
    finally:
        conn.close()
    notes = load_notes()
    out = []
    for r in rows:
        key = str(r["license_key"] or "")
        n = notes.get(key) or []
        last_note = str(n[-1].get("note", "") if n else "")
        if q in key.lower() or q in last_note.lower():
            out.append(r)
            if len(out) >= max(1, min(5000, int(limit or 500))):
                break
    return _rows_to_chunks(out, f"🔎 نتائج البحث ({TENANT}) — '{query}' | {len(out)}")

def purge_selected_revoked(keys, actor: str = "admin"):
    keys = [str(k or "").strip() for k in (keys or []) if str(k or "").strip()]
    if not keys:
        return 0, 0, []
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        removed = 0
        skipped_not_found = 0
        skipped_not_revoked = []
        for k in keys:
            row = conn.execute(
                "SELECT id, status FROM license_keys WHERE tenant=? AND license_key=?",
                (TENANT, k),
            ).fetchone()
            if not row:
                skipped_not_found += 1
                continue
            if str(row["status"] or "").lower() != "revoked":
                skipped_not_revoked.append(k)
                continue
            if ALLOW_HARD_DELETE:
                conn.execute("DELETE FROM license_events WHERE tenant=? AND license_key=?", (TENANT, k))
                conn.execute("DELETE FROM license_keys WHERE id=?", (int(row["id"]),))
            else:
                # Safety mode (default): keep records, just mark as revoked.
                conn.execute("UPDATE license_keys SET status='revoked' WHERE id=?", (int(row["id"]),))
            removed += 1
        conn.commit()
        return removed, skipped_not_found, skipped_not_revoked
    finally:
        conn.close()


def set_bot_commands():
    # So when you type "/" Telegram shows command list.
    try:
        requests.post(
            f"{API}/setMyCommands",
            json={"commands": BOT_COMMANDS},
            timeout=20,
        )
    except Exception:
        pass

def show_help(chat_id):
    send(
        chat_id,
        "📋 الأوامر:\n"
        "/key - توليد مفتاح (سيطلب يوزر العميل)\n"
        "/resetkey <KEY> [@username] - ريست المفتاح + نوت العميل\n"
        "/daykey [count] - مفاتيح يوم واحد (مغلق افتراضيًا)\n"
        "/delkey <KEY> - حذف كي واحد\n"
        "/delkeys <K1,K2,...> - حذف مجموعة كيات\n"
        "/purge_revoked <K1,K2,...> - حذف revoked محدد نهائيًا\n"
        "/stock [limit] - جرد الكيات (افتراضي: كل الكيات)\n"
        "/find <text> - بحث بالكي أو النوت\n"
        "/finduser <@username> - بحث مفاتيح العميل باليوزر\n"
        "/stockcsv - تصدير كل الكيات Excel CSV\n"
        "/alerts [limit] - آخر محاولات الكراك/IP\n"
        "/pending - عرض طلبات الموافقة (للمالك)\n"
        "/note <KEY> <NOTE> - إضافة نوت على كي\n"
        "/start - إظهار اللوحة\n"
        "\nأزرار اللوحة شغالة أيضًا.",
        keyboard=True,
    )


def approve_user(st, uid: str):
    uid = str(uid or "").strip()
    if not uid:
        return False
    if uid not in st["approved"]:
        st["approved"].append(uid)
    st["pending"].pop(uid, None)
    send(uid, "✅ تمت الموافقة عليك كأدمن", keyboard=True)
    send(OWNER_ID, f"✅ تمت الموافقة: {uid}", keyboard=True)
    return True

def process(msg, st):
    chat_id = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()

    if text.startswith("/pending") and chat_id in APPROVER_IDS:
        notify_all_pending(st)
        return

    if text.startswith("/approve") and chat_id in APPROVER_IDS:
        parts = text.split()
        if len(parts) >= 2:
            uid = parts[1].strip()
            if uid in HARD_DENY_IDS:
                send(OWNER_ID, f"⛔ هذا المستخدم محظور نهائيًا لهذا التيننت: {uid}", keyboard=True)
                return
            approve_user(st, uid)
        return

    if chat_id in HARD_DENY_IDS:
        owner_notify_denied(chat_id)
        send(chat_id, "⛔ غير مصرح لهذا البوت نهائيًا.", keyboard=True)
        return

    if chat_id not in st["approved"]:
        if chat_id not in st["pending"]:
            st["pending"][chat_id] = int(time.time())
            owner_notify_approval(chat_id)
        send(chat_id, "⛔ غير مصرح. تم إرسال طلب موافقة للمالك.", keyboard=True)
        return

    if text.startswith("/start"):
        send(chat_id, f"جاهز ✅\nTenant: {TENANT}", keyboard=True)
        show_help(chat_id)
        if chat_id == OWNER_ID:
            notify_all_pending(st)
        return

    if text in ("📋 الأوامر", "/help"):
        show_help(chat_id)
        return

    if text in ("♻️ ريست مفتاح",):
        st["reset_wait"][chat_id] = {"step": "key"}
        send(chat_id, "ارسل المفتاح الآن", keyboard=True)
        return

    if text in ("🗑️ حذف كي",):
        st.setdefault("del_wait", {})[chat_id] = "single"
        send(chat_id, "ارسل الكي الآن أو استخدم: /delkey LICENSE_KEY", keyboard=True)
        return

    if text in ("🗑️ حذف مجموعة",):
        st.setdefault("del_wait", {})[chat_id] = "multi"
        send(chat_id, "ارسل الكيات مفصولة بفاصلة (,) أو سطر جديد\nأو استخدم: /delkeys K1,K2", keyboard=True)
        return

    if text in ("🧹 حذف revoked محدد",):
        st.setdefault("purge_wait", {})[chat_id] = 1
        send(chat_id, "ارسل الكيات revoked فقط مفصولة بفاصلة أو سطر جديد\nأو استخدم: /purge_revoked K1,K2", keyboard=True)
        return

    if text in ("🔎 بحث كي",):
        st.setdefault("find_wait", {})[chat_id] = 1
        send(chat_id, "اكتب كلمة البحث الآن (جزء من الكي أو النوت)", keyboard=True)
        return

    if text in ("👤 بحث عميل",):
        st.setdefault("find_user_wait", {})[chat_id] = 1
        send(chat_id, "ارسل يوزر العميل الآن (مثال: @username)", keyboard=True)
        return

    if text in ("📊 اكسل الكيات", "/stockcsv"):
        fp = export_stock_csv()
        send_document(chat_id, fp, caption=f"📊 Stock Export - {TENANT}")
        send(chat_id, "✅ تم تصدير ملف الاكسل", keyboard=True)
        return

    if text in ("📦 جرد الكيات", "/stock"):
        for ch, md in get_key_inventory_text(50000):
            send(chat_id, ch, keyboard=False, markdown=md)
        send(chat_id, "✅ انتهى الجرد", keyboard=True)
        return

    if text in ("🚨 محاولات كراك", "/alerts"):
        send(chat_id, get_alerts_text(20), keyboard=True)
        return

    reset_ctx = st.get("reset_wait", {}).get(chat_id)
    if reset_ctx and not text.startswith("/"):
        if not isinstance(reset_ctx, dict):
            reset_ctx = {"step": "key"}
            st["reset_wait"][chat_id] = reset_ctx
        step = str(reset_ctx.get("step") or "key")
        if step == "key":
            key = text.strip()
            if not key:
                send(chat_id, "❌ ارسل المفتاح بشكل صحيح", keyboard=True)
                return
            reset_ctx["key"] = key
            reset_ctx["step"] = "username"
            _ask_username(chat_id, "ريست مفتاح")
            return

        if step == "username":
            key = str(reset_ctx.get("key") or "").strip()
            uname = _normalize_username(text)
            if not uname:
                send(chat_id, "❌ اليوزر غير صحيح. مثال: @username", keyboard=True)
                return
            send(chat_id, _format_client_usage(uname), keyboard=False, markdown=True)
            blocked = _client_blocking_keys(uname, ignore_key=key)
            warn_tag = ""
            if blocked:
                send(chat_id, _format_client_exists_warning(uname, blocked), keyboard=True, markdown=True)
                warn_tag = f" | open_keys:{len(blocked)}"
            ok, msg = admin_reset_license(tenant=TENANT, license_key=key, actor=f"tg:{chat_id}")
            if ok:
                add_note(key, chat_id, _client_note_marker(uname, "reset") + warn_tag)
                send(chat_id, f"✅ تم عمل Reset للمفتاح\n👤 العميل: @{uname}", keyboard=True)
            else:
                send(chat_id, f"❌ {msg}", keyboard=True)
            st["reset_wait"].pop(chat_id, None)
            return

    key_ctx = st.get("key_wait", {}).get(chat_id)
    if key_ctx and not text.startswith("/"):
        if not isinstance(key_ctx, dict):
            st["key_wait"].pop(chat_id, None)
            send(chat_id, "❌ انتهت العملية. اكتب /key من جديد", keyboard=True)
            return
        uname = _normalize_username(text)
        if not uname:
            send(chat_id, "❌ اليوزر غير صحيح. مثال: @username", keyboard=True)
            return
        send(chat_id, _format_client_usage(uname), keyboard=False, markdown=True)
        blocked = _client_blocking_keys(uname)
        active_keys = _active_keys_for_username(uname)
        warn_tag = ""
        if blocked:
            send(chat_id, _format_client_exists_warning(uname, blocked), keyboard=True, markdown=True)
            warn_tag = f" | open_keys:{len(blocked)}"
        if active_keys:
            lines = [f"⛔ العميل @{uname} عنده مفتاح نشط، ما نقدر نسوي مفتاح جديد."]
            lines.append("🔑 المفتاح/المفاتيح النشطة:")
            for k in active_keys[:5]:
                lines.append(f"• `{k}`")
            send(chat_id, "\n".join(lines), keyboard=True, markdown=True)
            try:
                add_note(active_keys[0], chat_id, _client_note_marker(uname, "keygen_blocked") + f" | active_keys:{len(active_keys)}")
            except Exception:
                pass
            st["key_wait"].pop(chat_id, None)
            return
        count = int(key_ctx.get("count") or 1)
        days = key_ctx.get("days")
        count = max(1, min(1, count))
        keys = create_keys(tenant=TENANT, count=count, actor=f"tg:{chat_id}", days=days)
        for k in keys:
            add_note(k, chat_id, _client_note_marker(uname, "keygen") + warn_tag)
            send_key(chat_id, k)
        if days:
            send(chat_id, f"✅ تم توليد {len(keys)} كي يومي\n👤 العميل: @{uname}", keyboard=True)
        else:
            send(chat_id, f"✅ تم توليد المفتاح\n👤 العميل: @{uname}", keyboard=True)
        st["key_wait"].pop(chat_id, None)
        return

    if st.get("note_wait", {}).get(chat_id) and not text.startswith("/"):
        key = st["note_wait"].pop(chat_id, "")
        add_note(key, chat_id, text)
        send(chat_id, f"✅ تم حفظ النوت للمفتاح:\n`{key}`", keyboard=True)
        return

    if st.get("del_wait", {}).get(chat_id) and not text.startswith("/"):
        mode = st["del_wait"].pop(chat_id, "")
        if mode == "single":
            ok, msg = admin_revoke_license(tenant=TENANT, license_key=text.strip(), actor=f"tg:{chat_id}")
            send(chat_id, "✅ تم حذف الكي" if ok else f"❌ {msg}", keyboard=True)
            return
        keys = [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]
        okc, miss = admin_revoke_many(tenant=TENANT, keys=keys, actor=f"tg:{chat_id}")
        send(chat_id, f"✅ تم حذف {okc} كي\n❌ غير موجود: {miss}", keyboard=True)
        return

    if st.get("find_wait", {}).get(chat_id) and not text.startswith("/"):
        st["find_wait"].pop(chat_id, None)
        for ch, md in find_keys_text(text, 500):
            send(chat_id, ch, keyboard=False, markdown=md)
        send(chat_id, "✅ انتهى البحث", keyboard=True)
        return

    if st.get("find_user_wait", {}).get(chat_id) and not text.startswith("/"):
        st["find_user_wait"].pop(chat_id, None)
        uname = _normalize_username(text)
        if not uname:
            send(chat_id, "❌ اليوزر غير صحيح. مثال: @username", keyboard=True)
            return
        send(chat_id, _format_client_usage(uname), keyboard=False, markdown=True)
        send(chat_id, _format_user_keys_by_username(uname), keyboard=True, markdown=True)
        return

    if st.get("purge_wait", {}).get(chat_id) and not text.startswith("/"):
        st["purge_wait"].pop(chat_id, None)
        keys = [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]
        removed, miss, not_rev = purge_selected_revoked(keys, actor=f"tg:{chat_id}")
        extra = f"\n⚠️ ليست revoked: {len(not_rev)}" if not_rev else ""
        send(chat_id, f"✅ تم حذف {removed} revoked نهائيًا\n❌ غير موجود: {miss}{extra}", keyboard=True)
        return

    if text.startswith("/note"):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            send(chat_id, "استخدم: /note LICENSE_KEY الملاحظة", keyboard=True)
            return
        key = parts[1].strip()
        note_text = parts[2].strip()
        add_note(key, chat_id, note_text)
        send(chat_id, f"✅ تم حفظ النوت للمفتاح:\n`{key}`", keyboard=True)
        return

    if text.startswith("/delkey"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "استخدم: /delkey LICENSE_KEY", keyboard=True)
            return
        ok, msg = admin_revoke_license(tenant=TENANT, license_key=parts[1].strip(), actor=f"tg:{chat_id}")
        send(chat_id, "✅ تم حذف الكي" if ok else f"❌ {msg}", keyboard=True)
        return

    if text.startswith("/delkeys"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "استخدم: /delkeys K1,K2,K3", keyboard=True)
            return
        keys = [x.strip() for x in parts[1].replace("\n", ",").split(",") if x.strip()]
        okc, miss = admin_revoke_many(tenant=TENANT, keys=keys, actor=f"tg:{chat_id}")
        send(chat_id, f"✅ تم حذف {okc} كي\n❌ غير موجود: {miss}", keyboard=True)
        return

    if text.startswith("/purge_revoked"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "استخدم: /purge_revoked K1,K2,K3", keyboard=True)
            return
        keys = [x.strip() for x in parts[1].replace("\n", ",").split(",") if x.strip()]
        removed, miss, not_rev = purge_selected_revoked(keys, actor=f"tg:{chat_id}")
        extra = f"\n⚠️ ليست revoked: {len(not_rev)}" if not_rev else ""
        send(chat_id, f"✅ تم حذف {removed} revoked نهائيًا\n❌ غير موجود: {miss}{extra}", keyboard=True)
        return

    if text.startswith("/stock"):
        parts = text.split()
        lim = 50000
        if len(parts) >= 2:
            try:
                lim = int(parts[1])
            except Exception:
                lim = 50000
        for ch, md in get_key_inventory_text(lim):
            send(chat_id, ch, keyboard=False, markdown=md)
        send(chat_id, "✅ انتهى الجرد", keyboard=True)
        return

    if text.startswith("/alerts"):
        parts = text.split()
        lim = 20
        if len(parts) >= 2:
            try:
                lim = int(parts[1])
            except Exception:
                lim = 20
        send(chat_id, get_alerts_text(lim), keyboard=True)
        return

    if text.startswith("/finduser"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "استخدم: /finduser @username", keyboard=True)
            return
        uname = _normalize_username(parts[1])
        if not uname:
            send(chat_id, "❌ اليوزر غير صحيح. مثال: @username", keyboard=True)
            return
        send(chat_id, _format_client_usage(uname), keyboard=False, markdown=True)
        send(chat_id, _format_user_keys_by_username(uname), keyboard=True, markdown=True)
        return

    if text.startswith("/find"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "استخدم: /find كلمة_بحث", keyboard=True)
            return
        for ch, md in find_keys_text(parts[1], 500):
            send(chat_id, ch, keyboard=False, markdown=md)
        send(chat_id, "✅ انتهى البحث", keyboard=True)
        return

    if text.startswith("/stockcsv"):
        fp = export_stock_csv()
        send_document(chat_id, fp, caption=f"📊 Stock Export - {TENANT}")
        send(chat_id, "✅ تم تصدير ملف الاكسل", keyboard=True)
        return

    if text.startswith("/resetkey") or text.startswith("/restkey"):
        parts = text.split()
        if len(parts) < 2:
            send(chat_id, "استخدم: /resetkey LICENSE_KEY [@username]", keyboard=True)
            return
        key = parts[1].strip()
        uname = _normalize_username(parts[2]) if len(parts) >= 3 else ""
        if not uname:
            st.setdefault("reset_wait", {})[chat_id] = {"step": "username", "key": key}
            _ask_username(chat_id, "ريست مفتاح")
            return
        send(chat_id, _format_client_usage(uname), keyboard=False, markdown=True)
        blocked = _client_blocking_keys(uname, ignore_key=key)
        warn_tag = ""
        if blocked:
            send(chat_id, _format_client_exists_warning(uname, blocked), keyboard=True, markdown=True)
            warn_tag = f" | open_keys:{len(blocked)}"
        ok, msg = admin_reset_license(tenant=TENANT, license_key=key, actor=f"tg:{chat_id}")
        if ok:
            add_note(key, chat_id, _client_note_marker(uname, "reset") + warn_tag)
            send(chat_id, f"✅ تم عمل Reset للمفتاح\n👤 العميل: @{uname}", keyboard=True)
        else:
            send(chat_id, f"❌ {msg}", keyboard=True)
        return

    if text in ("🔑 مفتاح جديد", "/key"):
        st.setdefault("key_wait", {})[chat_id] = {"count": 1, "days": None}
        _ask_username(chat_id, "مفتاح جديد")
        return

    if text in ("🔑 5 مفاتيح",):
        send(chat_id, "ℹ️ النظام الجديد: مفتاح واحد لكل عميل فقط. استخدم زر (🔑 مفتاح جديد) لكل عميل مع يوزره.", keyboard=True)
        return

    if text in ("⏰ كي يوم واحد", "/daykey") or text.startswith("/daykey"):
        if not ENABLE_DAYKEY:
            send(chat_id, "⛔ مفاتيح اليوم الواحد مغلقة لحماية المخزون. استخدم /key فقط.", keyboard=True)
            return
        st.setdefault("key_wait", {})[chat_id] = {"count": 1, "days": 1}
        _ask_username(chat_id, "كي يوم واحد")
        return

    if text.startswith("/key"):
        st.setdefault("key_wait", {})[chat_id] = {"count": 1, "days": None}
        _ask_username(chat_id, "مفتاح جديد")
        return

    send(chat_id, "استخدم الأزرار أو /key", keyboard=True)


def process_callback(cb, st):
    try:
        cb_id = cb.get("id")
        from_id = str((cb.get("from") or {}).get("id") or "")
        data = (cb.get("data") or "").strip()
        msg = cb.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        msg_id = msg.get("message_id")

        ok_txt = "تم التنفيذ ✅"

        if data.startswith("approve:"):
            if from_id not in APPROVER_IDS:
                ok_txt = "غير مصرح"
            else:
                uid = data.split(":", 1)[1].strip()
                if approve_user(st, uid):
                    requests.post(
                        f"{API}/editMessageReplyMarkup",
                        json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                        timeout=20,
                    )
                    requests.post(
                        f"{API}/editMessageText",
                        json={"chat_id": chat_id, "message_id": msg_id, "text": f"✅ تمت الموافقة: {uid}"},
                        timeout=20,
                    )
                else:
                    ok_txt = "فشل التنفيذ"

        elif data.startswith("note:"):
            key = data.split(":", 1)[1].strip()
            if from_id not in st.get("approved", []):
                ok_txt = "غير مصرح"
            else:
                st.setdefault("note_wait", {})[from_id] = key
                ok_txt = "اكتب النوت الآن"
                send(from_id, f"✍️ اكتب النوت الآن لهذا الكي:\n`{key}`", keyboard=True)

        elif data.startswith("shownote:"):
            key = data.split(":", 1)[1].strip()
            if from_id not in st.get("approved", []):
                ok_txt = "غير مصرح"
            else:
                send(from_id, get_notes_text(key), keyboard=True)
                ok_txt = "تم عرض النوت"

        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": ok_txt}, timeout=20)
    except Exception:
        pass


def main():
    init_db()
    set_bot_commands()
    st = load_state()
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"timeout": 30, "offset": st.get("offset", 0) + 1}, timeout=40)
            data = r.json()
            if not data.get("ok"):
                time.sleep(2)
                continue
            for up in data.get("result", []):
                st["offset"] = up.get("update_id", st.get("offset", 0))
                msg = up.get("message")
                if msg and msg.get("chat") and msg["chat"].get("type") == "private":
                    process(msg, st)
                cb = up.get("callback_query")
                if cb:
                    process_callback(cb, st)
            save_state(st)
        except Exception:
            time.sleep(2)

if __name__ == "__main__":
    main()
