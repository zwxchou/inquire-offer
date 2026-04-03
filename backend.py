import base64
import hmac
import io
import json
import os
import shutil
import sqlite3
import threading
import time
import traceback
import zipfile
from datetime import datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

try:
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
except ImportError:
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "sales.db"
STATE_KEY = "quote_procurement_system_v1"
BACKUP_DIR = ROOT / "backups"
DAILY_DIR = BACKUP_DIR / "daily"
LATEST_DIR = BACKUP_DIR / "latest"
CARD_DIR = ROOT / "customer_cards"
CARD_MAX_BYTES = int(os.environ.get("SALES_CARD_MAX_BYTES", str(20 * 1024 * 1024)))
AUTH_USER = os.environ.get("SALES_AUTH_USER", "admin")
AUTH_PASS = os.environ.get("SALES_AUTH_PASS", "Sales@2026")
AUTH_REALM = os.environ.get("SALES_AUTH_REALM", "SalesQuoteSystem")
AUTH_EXEMPT_PATHS = set(["/healthz"])


def ensure_dirs():
    for d in (BACKUP_DIR, DAILY_DIR, LATEST_DIR, CARD_DIR):
        if not d.exists():
            d.mkdir(parents=True)


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
              key TEXT PRIMARY KEY,
              data TEXT NOT NULL,
              updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def load_state():
    conn = get_conn()
    try:
        row = conn.execute("SELECT data FROM app_state WHERE key = ?", (STATE_KEY,)).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0])
        except Exception:
            return {}
    finally:
        conn.close()


def _backup_latest():
    ensure_dirs()
    state = load_state()
    (LATEST_DIR / "state_latest.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if DB_PATH.exists():
        shutil.copy2(str(DB_PATH), str(LATEST_DIR / "sales_latest.db"))


def save_state(state):
    payload = json.dumps(state, ensure_ascii=False)
    conn = get_conn()
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            INSERT INTO app_state(key, data, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
              data=excluded.data,
              updated_at=datetime('now', 'localtime')
            """,
            (STATE_KEY, payload),
        )
        conn.commit()
    finally:
        conn.close()
    _backup_latest()


def backup_daily():
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    state = load_state()
    json_path = DAILY_DIR / ("state_%s.json" % stamp)
    db_path = DAILY_DIR / ("sales_%s.db" % stamp)
    json_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if DB_PATH.exists():
        shutil.copy2(str(DB_PATH), str(db_path))
    return str(json_path)


def backup_scheduler():
    while True:
        now = datetime.now()
        next_run = now.replace(hour=18, minute=15, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        sleep_seconds = int((next_run - now).total_seconds())
        if sleep_seconds < 1:
            sleep_seconds = 1
        time.sleep(sleep_seconds)
        try:
            out = backup_daily()
            print("[backup-daily] created:", out)
        except Exception as exc:
            print("[backup-daily] failed:", exc)
            traceback.print_exc()


def save_card_image(customer_id, filename, content_b64):
    ensure_dirs()
    raw_name = (filename or "").strip().lower()
    ext = ".jpg"
    for allowed in (".png", ".jpg", ".jpeg", ".webp"):
        if raw_name.endswith(allowed):
            ext = allowed
            break
    safe_customer = "".join(ch for ch in (customer_id or "CUNKNOWN") if ch.isalnum() or ch in ("_", "-"))
    if not safe_customer:
        safe_customer = "CUNKNOWN"
    safe_customer = safe_customer[:40]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_name = "%s_%s%s" % (safe_customer, stamp, ext)
    target = CARD_DIR / final_name
    try:
        data = base64.b64decode(content_b64, validate=True)
    except Exception:
        raise ValueError("invalid base64 image content")
    if len(data) > CARD_MAX_BYTES:
        raise ValueError("image too large (max %dMB)" % max(1, CARD_MAX_BYTES // (1024 * 1024)))
    target.write_bytes(data)
    return "/customer_cards/%s" % final_name


def build_cards_zip_bytes():
    ensure_dirs()
    files = [p for p in CARD_DIR.glob("*") if p.is_file()]
    files.sort(key=lambda p: p.name.lower())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if not files:
            zf.writestr("README.txt", "No card images found.")
        for p in files:
            zf.write(str(p), arcname=p.name)
    return buf.getvalue()


def health_report():
    db_ok = True
    db_error = ""
    try:
        conn = get_conn()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    backup_ok = True
    backup_error = ""
    try:
        ensure_dirs()
        probe = LATEST_DIR / ".writable_probe"
        probe.write_text("ok", encoding="utf-8")
        try:
            probe.unlink()
        except Exception:
            pass
    except Exception as exc:
        backup_ok = False
        backup_error = str(exc)

    return {
        "ok": db_ok and backup_ok,
        "db_ok": db_ok,
        "backup_ok": backup_ok,
        "db_error": db_error,
        "backup_error": backup_error,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        SimpleHTTPRequestHandler.__init__(self, *args, **kwargs)

    def translate_path(self, path):
        # Python 3.6 does not support the "directory=" argument in handler init.
        # Keep static-file root locked to project ROOT.
        path = path.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in path.split("/") if p and p not in (".", "..")]
        target = ROOT
        for part in parts:
            target = target / part
        return str(target)

    def _send_json(self, status_code, body, with_body=True):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if with_body:
            self.wfile.write(raw)

    def _send_bytes(self, status_code, raw, content_type, filename=None, with_body=True):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        self.end_headers()
        if with_body:
            self.wfile.write(raw)

    def _send_plain(self, status_code, body_text):
        raw = body_text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _is_authorized(self):
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            return False
        token = auth_header[6:].strip()
        if not token:
            return False
        try:
            decoded = base64.b64decode(token).decode("utf-8")
        except Exception:
            return False
        if ":" not in decoded:
            return False
        username, password = decoded.split(":", 1)
        return hmac.compare_digest(username, AUTH_USER) and hmac.compare_digest(password, AUTH_PASS)

    def _require_auth(self, path):
        if path in AUTH_EXEMPT_PATHS:
            return True
        if self._is_authorized():
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="%s", charset="UTF-8"' % AUTH_REALM)
        if path.startswith("/api/"):
            body = json.dumps({"ok": False, "error": "unauthorized"}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = "Unauthorized".encode("utf-8")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        return False

    def _safe(self, fn):
        try:
            fn()
        except Exception as exc:
            print("[handler-error]", exc)
            traceback.print_exc()
            try:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            except Exception:
                pass

    def do_GET(self):
        def run():
            path = urlparse(self.path).path
            if not self._require_auth(path):
                return
            if path == "/api/state":
                self._send_json(HTTPStatus.OK, {"ok": True, "state": load_state()})
                return
            if path == "/api/download-cards":
                payload = build_cards_zip_bytes()
                filename = "customer_cards_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M%S")
                self._send_bytes(HTTPStatus.OK, payload, "application/zip", filename=filename)
                return
            if path == "/healthz":
                report = health_report()
                status = HTTPStatus.OK if report["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
                self._send_json(status, report)
                return
            SimpleHTTPRequestHandler.do_GET(self)

        self._safe(run)

    def do_HEAD(self):
        def run():
            path = urlparse(self.path).path
            if not self._require_auth(path):
                return
            if path == "/api/state":
                self._send_json(HTTPStatus.OK, {"ok": True, "state": load_state()}, with_body=False)
                return
            if path == "/api/download-cards":
                payload = build_cards_zip_bytes()
                filename = "customer_cards_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M%S")
                self._send_bytes(HTTPStatus.OK, payload, "application/zip", filename=filename, with_body=False)
                return
            if path == "/healthz":
                report = health_report()
                status = HTTPStatus.OK if report["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
                self._send_json(status, report, with_body=False)
                return
            SimpleHTTPRequestHandler.do_HEAD(self)

        self._safe(run)

    def do_PUT(self):
        def run():
            path = urlparse(self.path).path
            if not self._require_auth(path):
                return
            if path != "/api/state":
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("state must be object")

            if payload == {}:
                existing = load_state()
                if existing:
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        {"ok": False, "error": "refuse to overwrite non-empty state with empty object"},
                    )
                    return

            save_state(payload)
            self._send_json(HTTPStatus.OK, {"ok": True})

        self._safe(run)

    def do_POST(self):
        def run():
            path = urlparse(self.path).path
            if not self._require_auth(path):
                return
            if path != "/api/upload-card":
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be object")
            customer_id = str(payload.get("customerId") or "").strip()
            filename = str(payload.get("filename") or "").strip()
            content_b64 = str(payload.get("contentBase64") or "").strip()
            if not customer_id:
                raise ValueError("customerId required")
            if not filename:
                raise ValueError("filename required")
            if not content_b64:
                raise ValueError("contentBase64 required")
            image_path = save_card_image(customer_id, filename, content_b64)
            self._send_json(HTTPStatus.OK, {"ok": True, "imagePath": image_path})

        self._safe(run)

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        if not self._require_auth(path):
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET,PUT,POST,OPTIONS,HEAD")
        self.end_headers()

    def log_message(self, fmt, *args):
        return


def main():
    ensure_dirs()
    init_db()
    _backup_latest()
    threading.Thread(target=backup_scheduler, daemon=True).start()

    port = int(os.environ.get("SALES_PORT", "5173"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print("Serving on http://127.0.0.1:%s" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
