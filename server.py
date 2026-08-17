#!/usr/bin/env python3
# 二合一本地服务器：静态托管 workspace + POST /api/refresh 触发全局采集（重写 HTML）。
# 启动：python3 server.py  （默认端口 8789）
import os, json, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

WS = os.path.dirname(os.path.abspath(__file__))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WS, **k)

    def do_POST(self):
        if self.path.rstrip("/") == "/api/refresh":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(body or b"{}")
                    days = payload.get("days")
                except Exception:
                    days = None
                # 延迟导入并强制重载，确保最新代码生效
                sys.path.insert(0, WS)
                import refresh_lib
                import importlib
                refresh_lib = importlib.reload(refresh_lib)
                res = refresh_lib.run_refresh(days=int(days) if days else None)
                self.send_json(200, res)
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return
        self.send_json(404, {"ok": False, "error": "not found"})

    def send_json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # 静默常规静态请求日志，只保留刷新记录由 refresh_lib 打印
        if "/api/refresh" in (self.path or ""):
            sys.stderr.write("[server] " + (fmt % args) + "\n")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8789
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[server] serving {WS} at http://127.0.0.1:{port}/")
    print(f"[server] refresh endpoint: POST http://127.0.0.1:{port}/api/refresh")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] stopped")
