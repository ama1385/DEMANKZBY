"""Extract / re-embed base64 assets in proxy.py."""
import base64
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
PROXY = BACKEND / "proxy.py"
PROXY_NO_AUTH = BACKEND / "proxy_no_auth.py"
KEYS = ("/index.html", "/style.css", "/script.js")
UI_PATCH_KEYS = ("/index.html", "/style.css", "/script.js")


def extract_b64_for_key(src: str, key: str) -> str:
    pat = re.escape(f"'{key}'") + r"\s*:\s*\("
    m = re.search(pat, src)
    if not m:
        raise ValueError(f"Key {key} not found")
    i = m.end()
    parts = []
    while i < len(src):
        if src[i] in " \t\n\r":
            i += 1
            continue
        if src[i] == ")":
            break
        if src[i] not in '"\'':
            raise ValueError(f"Unexpected at {i}: {src[i: i + 20]!r}")
        q = src[i]
        i += 1
        start = i
        while i < len(src) and src[i] != q:
            if src[i] == "\\":
                i += 2
            else:
                i += 1
        parts.append(src[start:i])
        i += 1
    return "".join(parts)


def decode_asset(key: str) -> bytes:
    src = PROXY.read_text(encoding="utf-8")
    b64 = extract_b64_for_key(src, key)
    return base64.b64decode(b64)


def encode_lines(b: bytes, width: int = 76) -> str:
    b64 = base64.b64encode(b).decode("ascii")
    lines = []
    for j in range(0, len(b64), width):
        lines.append('        "' + b64[j : j + width] + '"')
    return "\n".join(lines)


def replace_embedded(key: str, new_bytes: bytes, proxy_file: Path | None = None) -> None:
    target = proxy_file or PROXY
    src = target.read_text(encoding="utf-8")
    pat = re.compile(
        r"(" + re.escape(f"'{key}'") + r"\s*:\s*\(\s*\n)(.*?)(\n\s*\),)",
        re.DOTALL,
    )
    m = pat.search(src)
    if not m:
        raise ValueError(f"Block for {key} not found in {target.name}")
    new_lines = encode_lines(new_bytes)
    new_block = m.group(1) + new_lines + m.group(3)
    src = src[: m.start()] + new_block + src[m.end() :]
    target.write_text(src, encoding="utf-8")


if __name__ == "__main__":
    import sys

    out = Path(__file__).resolve().parent / "ui_work"
    if sys.argv[-1] == "extract":
        out.mkdir(exist_ok=True)
        for k in KEYS:
            name = k.strip("/").replace(".", "_")
            p = out / name
            p.write_bytes(decode_asset(k))
            print("wrote", p, len(p.read_bytes()), "bytes")
    elif sys.argv[-1] == "embed":
        for k in KEYS:
            name = k.strip("/").replace(".", "_")
            p = out / name
            replace_embedded(k, p.read_bytes())
            print("embedded", k)
    elif sys.argv[-1] == "embed-ui":
        for proxy_f in (PROXY, PROXY_NO_AUTH):
            for k in UI_PATCH_KEYS:
                name = k.strip("/").replace(".", "_")
                p = out / name
                replace_embedded(k, p.read_bytes(), proxy_f)
            print("embedded index+style+script ->", proxy_f.name)
    else:
        print("usage: embed_tools.py extract|embed|embed-ui")
