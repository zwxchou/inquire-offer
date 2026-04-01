import json
import os
import shutil
import sqlite3
import threading
import time
import base64
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "sales.db"
STATE_KEY = "quote_procurement_system_v1"
BACKUP_DIR = ROOT / "backups"
DAILY_DIR = BACKUP_DIR / "daily"
LATEST_DIR = BACKUP_DIR / "latest"
CARD_DIR = ROOT / "customer_cards"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
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


def load_state_from_db() -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT data FROM app_state WHERE key = ?", (STATE_KEY,)).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return {}
    finally:
        conn.close()


def save_state_to_db(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
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
    backup_latest_snapshot()


def ensure_backup_dirs() -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)


def ensure_card_dir() -> None:
    CARD_DIR.mkdir(parents=True, exist_ok=True)


def save_card_image(customer_id: str, filename: str, content_b64: str) -> str:
    ensure_card_dir()
    raw_name = (filename or "").strip().lower()
    ext = ".jpg"
    for allowed in (".png", ".jpg", ".jpeg", ".webp"):
        if raw_name.endswith(allowed):
            ext = allowed
            break
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("unsupported image type")
    safe_customer = "".join(ch for ch in (customer_id or "CUNKNOWN") if ch.isalnum() or ch in ("_", "-"))[:40] or "CUNKNOWN"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_name = f"{safe_customer}_{stamp}{ext}"
    target = CARD_DIR / final_name
    try:
        data = base64.b64decode(content_b64, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 image content") from exc
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("image too large (max 8MB)")
    target.write_bytes(data)
    return f"/customer_cards/{final_name}"


def _write_snapshot(target_dir: Path, stamp: str) -> Path:
    state = load_state_from_db()
    json_path = target_dir / f"state_{stamp}.json"
    db_path = target_dir / f"sales_{stamp}.db"
    json_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, db_path)
    return json_path


def backup_latest_snapshot() -> None:
    ensure_backup_dirs()
    state = load_state_from_db()
    (LATEST_DIR / "state_latest.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, LATEST_DIR / "sales_latest.db")


def backup_daily() -> Path:
    ensure_backup_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _write_snapshot(DAILY_DIR, stamp)


def run_daily_backup_scheduler() -> None:
    # Runs daily at 18:15 local time.
    while True:
        now = datetime.now()
        next_run = now.replace(hour=18, minute=15, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        wait_seconds = max(1, int((next_run - now).total_seconds()))
        time.sleep(wait_seconds)
        try:
            out = backup_daily()
            print(f"[backup-daily] created: {out}")
        except Exception as exc:
            print(f"[backup-daily] failed: {exc}")


def health_report() -> dict:
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
        ensure_backup_dirs()
        probe = LATEST_DIR / ".writable_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
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
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(HTTPStatus.OK, {"ok": True, "state": load_state_from_db()})
            return
        if path == "/healthz":
            report = health_report()
            status = HTTPStatus.OK if report["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(status, report)
            return
        return super().do_GET()

    def do_PUT(self):
        path = urlparse(self.path).path
        if path != "/api/state":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("state must be object")
            # Protection: avoid accidental full wipe with {} when DB already has data.
            if payload == {}:
                existing = load_state_from_db()
                if existing:
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        {"ok": False, "error": "refuse to overwrite non-empty state with empty object"},
                    )
                    return
            save_state_to_db(payload)
            self._send_json(HTTPStatus.OK, {"ok": True})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/upload-card":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
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
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET,PUT,POST,OPTIONS")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        # Disable default logging to avoid potential reverse-DNS stalls.
        return


def main() -> None:
    port = int(os.environ.get("SALES_PORT", "5173"))
    init_db()
    ensure_backup_dirs()
    ensure_card_dir()
    backup_latest_snapshot()
    threading.Thread(target=run_daily_backup_scheduler, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print(f"Serving on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
