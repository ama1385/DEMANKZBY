#!/usr/bin/env python3
import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from license_core import init_db, create_keys

HOST = os.environ.get("ADMIN_HUB_HOST", "0.0.0.0")
PORT = int(os.environ.get("ADMIN_HUB_PORT", "8111"))
ADMIN_TOKEN = (os.environ.get("ADMIN_HUB_TOKEN") or "").strip()

HTML = """<!doctype html>
<html><head><meta charset='utf-8'><title>Admin Key Hub</title>
<style>body{font-family:Arial;background:#111;color:#eee;max-width:700px;margin:30px auto}input,select,button{padding:10px;margin:6px 0;width:100%}button{background:#6d5efc;color:#fff;border:0;border-radius:8px}pre{white-space:pre-wrap;background:#1d1d1d;padding:12px;border-radius:8px}</style>
</head><body>
<h2>🔐 Admin Key Hub</h2>
<label>Admin Token</label><input id='tok' type='password'>
<label>Tenant</label><select id='tenant'><option>DEMAN.STORE</option><option>DEMAN.SOTRE</option></select>
<label>Count</label><input id='count' type='number' value='1' min='1' max='200'>
<button onclick='go()'>Generate</button>
<pre id='out'></pre>
<script>
async function go(){
  const t=document.getElementById('tok').value.trim();
  const tenant=document.getElementById('tenant').value;
  const count=parseInt(document.getElementById('count').value||'1',10);
  const r=await fetch('/api/admin/internal-keygen',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+t},body:JSON.stringify({tenant,count})});
  const j=await r.json().catch(()=>({error:'bad json'}));
  document.getElementById('out').textContent=JSON.stringify(j,null,2);
}
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if urlparse(self.path).path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())
            return
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/admin/internal-keygen":
            self.send_error(404)
            return
        auth = (self.headers.get("Authorization") or "").strip()
        if (not ADMIN_TOKEN) or auth != f"Bearer {ADMIN_TOKEN}":
            self._json(403, {"error": "Forbidden"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode() if n else "{}")
            tenant = str(body.get("tenant") or "DEMAN.STORE").strip().upper()
            count = int(body.get("count", 1) or 1)
            keys = create_keys(tenant=tenant, count=count, actor="admin-web")
            self._json(200, {"ok": True, "tenant": tenant, "count": len(keys), "keys": keys})
        except Exception as e:
            self._json(500, {"error": str(e)})

if __name__ == "__main__":
    init_db()
    print(f"Admin hub on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
