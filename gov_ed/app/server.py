"""零依赖 HTTP 服务（社会治理版）。

页面：
  /           诉求工作台（接线员/坐席）
  /report?t=xxx  市民上报页
  /duty       值班人员处置台（Human-in-the-loop）
"""
from __future__ import annotations

import json
import mimetypes
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import comms, config, demo_cases, llm
from .pipeline import Pipeline
from .store import Store

STORE = Store()
PIPELINE = Pipeline(STORE)
_STARTED = time.time()


def lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def _public_base(host_header: str) -> str:
    import os
    override = os.environ.get("GOV_PUBLIC_URL")
    if override:
        return override.rstrip("/")
    host = host_header or f"127.0.0.1:{config.PORT}"
    if host.startswith("127.0.0.1") or host.startswith("localhost"):
        ips = lan_ips()
        if ips:
            port = host.rsplit(":", 1)[-1] if ":" in host else str(config.PORT)
            host = f"{ips[0]}:{port}"
    return f"http://{host}"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _service_alive(port: int) -> bool:
    import urllib.request as _req
    for h in ("127.0.0.1", "localhost"):
        try:
            with _req.urlopen(f"http://{h}:{port}/health", timeout=0.8) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("ok") and "version" in data:
                    return True
        except Exception:
            continue
    return False


def _queue_payload(base: str) -> list[dict[str, Any]]:
    out = []
    now = time.time()
    for pos, c in enumerate(STORE.window(), start=1):
        risks = (c.get("screening") or {}).get("risks") or []
        out.append({
            "id": c["id"], "name": c["name"], "location": (c.get("location") or "")[:24],
            "text": (c.get("text") or "")[:36],
            "level": c.get("level"), "stage": c["stage"], "position": pos,
            "risk": risks[0]["name"] if risks else "",
            "crowd": c.get("crowd"),
            "wait_minutes": max(0, int((now - c["created_ts"]) / 60)),
            "created_at": c["created_at"],
            "report_url": f"{base}/report?t={c['token']}",
        })
    return out


def _state() -> dict[str, Any]:
    tickets = []
    for t in STORE.pending_tickets():
        tickets.append({**t, "overdue": time.time() > t["due_ts"]})
    return {
        "stats": STORE.stats(),
        "queue": _queue_payload(STORE.__dict__.setdefault("_base", f"http://127.0.0.1:{config.PORT}")),
        "tickets": tickets,
        "audit": STORE.audit[-24:][::-1],
        "cases": [{"key": c["key"], "title": c["title"], "tag": c["tag"]} for c in demo_cases.CASES],
        "meta": {
            "version": config.VERSION, "system": config.SYSTEM_NAME, "agents": 6,
            "screened": 10, "uptime": int(time.time() - _STARTED),
            "llm": llm.available(), "llm_model": config.LLM_MODEL,
            "disclaimer": config.DISCLAIMER,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = f"GovOS/{config.VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _error(self, status: int, message: str) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("请求体不是合法 JSON")

    def _file(self, path: Path) -> None:
        if not path.exists():
            self._error(404, "not found")
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif path.suffix in (".css", ".js", ".svg"):
            ctype += "; charset=utf-8"
        self._send(path.read_bytes(), ctype, cache="no-cache")

    def _base(self) -> str:
        return _public_base(self.headers.get("Host", ""))

    def _full_case(self, case: dict[str, Any]) -> dict[str, Any]:
        base = self._base()
        return {
            **case,
            "position": STORE.position(case),
            "report_url": f"{base}/report?t={case['token']}",
            "tickets": [STORE.tickets[t] for t in case.get("hitl", []) if t in STORE.tickets],
        }

    def _report_view(self, case: dict[str, Any]) -> dict[str, Any]:
        snapshot = STORE.queue_snapshot(case)
        level = case.get("level") or 3
        comms_view = comms.reply(case, level)
        return {
            "id": case["id"], "name": case["name"], "stage": case["stage"],
            "level": level, "position": STORE.position(case),
            "notice": comms_view["primary"], "taboos": comms_view["taboos"],
            "last_report": (case.get("reports") or [None])[-1],
            "updated_at": case["updated_at"], "taken_over": case["stage"] == "已接管",
        }

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        STORE.__dict__["_base"] = self._base()

        if path in ("/", "/index.html"):
            return self._file(config.TEMPLATE_DIR / "gov.html")
        if path in ("/report", "/report.html"):
            return self._file(config.TEMPLATE_DIR / "report.html")
        if path in ("/duty", "/duty.html"):
            return self._file(config.TEMPLATE_DIR / "duty.html")
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            target = (config.STATIC_DIR / name).resolve()
            if config.STATIC_DIR.resolve() not in target.parents:
                return self._error(403, "forbidden")
            return self._file(target)

        if path == "/api/state":
            return self._json(_state())
        if path == "/api/demo/cases":
            return self._json({"cases": demo_cases.CASES})
        if path == "/health":
            return self._json({"ok": True, "version": config.VERSION, "store": len(STORE.cases)})
        if path == "/api/audit":
            return self._json({"events": STORE.audit[-60:][::-1]})
        if path.startswith("/api/case/"):
            cid = path.rsplit("/", 1)[-1]
            case = STORE.get_case(cid)
            if not case:
                return self._error(404, "诉求不存在")
            return self._json(self._full_case(case))
        if path.startswith("/api/report/"):
            token = path.rsplit("/", 1)[-1]
            case = STORE.get_by_token(token)
            if not case:
                return self._error(404, "链接无效")
            return self._json(self._report_view(case))
        return self._error(404, "not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        STORE.__dict__["_base"] = self._base()
        try:
            body = self._body()
        except ValueError as exc:
            return self._error(400, str(exc))

        try:
            if path == "/api/intake":
                if not (body.get("text") or "").strip():
                    return self._error(400, "诉求内容不能为空")
                case = PIPELINE.intake(body)
                return self._json(self._full_case(case))

            if path == "/api/report":
                token = body.get("token") or ""
                case = STORE.get_by_token(token)
                if not case:
                    return self._error(404, "链接无效")
                return self._json(PIPELINE.recheck(case, body))

            if path == "/api/hitl":
                tid = body.get("ticket_id") or ""
                action = body.get("action") or ""
                if action not in ("accept", "agree", "upgrade1", "upgrade2", "downgrade", "missing", "takeover"):
                    return self._error(400, "未知处置动作")
                level = None
                if action == "upgrade1":
                    level = 1
                elif action == "upgrade2":
                    level = 2
                elif action == "downgrade":
                    level = int(body.get("level") or 3)
                    if level <= 2:
                        return self._error(400, "降级不能降到二级及以下，请直接用「接管」")
                mapped = "accept" if action in ("accept", "takeover") else \
                    ("upgrade" if action in ("upgrade1", "upgrade2") else action)
                t = STORE.ticket_action(tid, mapped, body.get("duty") or "值班人员",
                                        (body.get("note") or "").strip(), level)
                if not t:
                    return self._error(404, "工单不存在")
                case = STORE.get_case(t["case_id"])
                return self._json({"ok": True, "ticket": t,
                                   "case": self._full_case(case) if case else None})

            if path == "/api/demo/seed":
                created = []
                for c in demo_cases.CASES:
                    if c["key"] in ("policy",):
                        continue
                    case = PIPELINE.intake({**c["payload"], "source2": "seed"})
                    created.append({"id": case["id"], "name": case["name"], "level": case["level"]})
                return self._json({"ok": True, "created": created})

            if path == "/api/reset":
                STORE.reset()
                return self._json({"ok": True})

            if path == "/api/report/tone":
                token = body.get("token") or ""
                case = STORE.get_by_token(token)
                if not case:
                    return self._error(404, "诉求不存在")
                result = comms.reply(case, case.get("level") or 3, message=body.get("message") or "")
                return self._json(result)

            return self._error(404, "not found")
        except KeyError as exc:
            self._error(404, f"对象不存在: {exc}")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._error(500, f"服务异常: {exc}")


def _monitor_loop() -> None:
    while True:
        try:
            PIPELINE.tick()
        except Exception:
            import traceback
            traceback.print_exc()
        time.sleep(config.MONITOR_TICK)


def serve(host: str | None = None, port: int | None = None, open_browser: bool = True) -> None:
    host = host or config.HOST
    port = port or config.PORT

    if _service_alive(port):
        print()
        print("=" * 62)
        print(f" {port} 端口已经有一个 GovOS 在运行了，不用再启动一次。")
        print(f" 直接打开：http://127.0.0.1:{port}/")
        print("=" * 62)
        if open_browser:
            import webbrowser
            try:
                webbrowser.open(f"http://127.0.0.1:{port}/")
            except Exception:
                pass
        return

    try:
        httpd = _Server((host, port), Handler)
    except OSError as exc:
        print()
        print("=" * 62)
        print(f" 启动失败：端口 {port} 被占用（{exc}）")
        print(f" 换端口启动：py -3 run.py --port {port + 10}")
        print("=" * 62)
        raise SystemExit(1)
    threading.Thread(target=_monitor_loop, daemon=True).start()

    print("=" * 62)
    print(f" {config.SYSTEM_NAME} · {config.SYSTEM_SUB}  v{config.VERSION}")
    print("=" * 62)
    print(f" 诉求工作台  http://127.0.0.1:{port}/")
    print(f" 值班处置台  http://127.0.0.1:{port}/duty")
    print(f" 市民上报页  http://127.0.0.1:{port}/report")
    if host in ("0.0.0.0", "::", ""):
        for ip in lan_ips():
            print(f"  局域网: http://{ip}:{port}/")
    print(" 浏览器没自动打开？把上面的地址复制到浏览器即可。")
    print(f" {config.DISCLAIMER}")
    print("=" * 62)

    if open_browser:
        import webbrowser
        try:
            threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
