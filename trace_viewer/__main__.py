from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .normalize import public_event
from .store import HistoryStore, StoreError

STATIC = Path(__file__).parent / "static"


def handler_for(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log search terms, conversation text or file contents.
            pass

        def send_body(self, body, status=200, kind="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if host not in allowed or (origin and origin not in {"http://" + h for h in allowed}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.send_body({"error": "仅允许本机页面访问。"}, 403)
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path == "/api/info":
                    return self.send_body(store.info())
                if path == "/api/sessions":
                    sessions, warning = store.list_sessions()
                    return self.send_body({"sessions": [{k: v for k, v in s.items() if not k.startswith("_")} for s in sessions], "warning": warning})
                parts = [unquote(x) for x in path.split("/") if x]
                if len(parts) >= 3 and parts[:2] == ["api", "sessions"]:
                    sid = parts[2]
                    if len(parts) == 5 and parts[3] == "items":
                        return self.send_body(store.detail(sid, parts[4], query.get("turn", [None])[0]))
                    if len(parts) == 3:
                        result = store.load(sid, refresh=query.get("refresh") == ["1"])
                        return self.send_body({**result, "events": [public_event(e) for e in result["events"]]})
                assets = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/process.js": "process.js", "/process.css": "process.css", "/icon.svg": "icon.svg"}
                if path in assets:
                    file = STATIC / assets[path]
                    kind = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
                    return self.send_body(file.read_bytes(), kind=kind + ("; charset=utf-8" if kind.startswith("text/") or "javascript" in kind else ""))
                return self.send_body({"error": "地址不存在。"}, 404)
            except KeyError as exc:
                return self.send_body({"error": str(exc.args[0])}, 404)
            except (StoreError, sqlite3.Error, OSError, ValueError) as exc:
                return self.send_body({"error": "读取失败：" + str(exc)}, 503)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="只读本机 Codex 执行记录。")
    parser.add_argument("--codex-home", help="Codex 数据目录，默认 CODEX_HOME 或 ~/.codex")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="服务就绪后打开默认浏览器")
    args = parser.parse_args()
    store = HistoryStore(args.codex_home)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(store))
    except OSError as exc:
        parser.exit(1, f"无法启动本地服务：{exc}。请换一个 --port，或打开已运行的页面。\n")
    print(f"Codex Trace: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Read-only source: {store.home}", flush=True)
    if args.open:
        threading.Thread(target=webbrowser.open, args=(f"http://127.0.0.1:{server.server_port}",), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
