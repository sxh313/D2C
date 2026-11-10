"""Write a fixed React project, build it, and host its static preview locally."""

import os
import base64
import binascii
import re
import signal
import shutil
import socket
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from design2code.settings import Settings, get_settings
from design2code.storage import connect, get_input, get_source_set


TEMPLATE = Path(__file__).resolve().parent / "template"
_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()
_build_lock = threading.Lock()
_build_processes: dict[str, subprocess.Popen[str]] = {}


class PreviewHandler(SimpleHTTPRequestHandler):
    def _select_candidate(self) -> bool:
        path = unquote(urlsplit(self.path).path)
        match = re.fullmatch(r"/(run_[a-zA-Z0-9_-]+)/(candidate(?:-2)?)(/.*)?", path)
        if not match:
            self.send_error(404)
            return False
        run_id, candidate, resource = match.groups()
        self.directory = str(get_settings().runtime_dir / "runs" / run_id / candidate / "dist")
        self.path = resource or "/"
        return True

    def do_GET(self) -> None:
        if self._select_candidate():
            if self.path == "/__d2c_selection.js":
                self._send_preview_content(Path(__file__).with_name("selection_bridge.js"), "text/javascript; charset=utf-8")
            elif self.path in {"/", "/index.html"}:
                self._send_preview_content(Path(self.directory) / "index.html", "text/html; charset=utf-8", inject=True)
            else:
                super().do_GET()

    def _send_preview_content(self, path: Path, content_type: str, inject: bool = False) -> None:
        try:
            content = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        if inject:
            script = b'<script src="./__d2c_selection.js"></script>'
            if b"</body>" in content:
                content = content.replace(b"</body>", script + b"</body>", 1)
            else:
                content += script
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_HEAD(self) -> None:
        if self._select_candidate():
            super().do_HEAD()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; connect-src 'none'; object-src 'none'; base-uri 'none'")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class LocalPreviewServer(ThreadingHTTPServer):
    # SO_REUSEADDR on Windows permits two servers to bind the same port.
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _child_env() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
               "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PNPM_HOME", "HOME"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    capture_output=True, timeout=10, check=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW, env=_child_env())
            if result.returncode and process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def cancel_build(run_id: str) -> bool:
    """Stop only the live process tree registered for this run."""
    with _build_lock:
        process = _build_processes.get(run_id)
        if process is None or process.poll() is not None:
            return False
        _stop_process_tree(process)
        return True


def _run_build_command(run_id: str, args: list[str], candidate: Path, timeout: int) -> dict[str, Any]:
    with _build_lock:
        with connect() as db:
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "BUILDING":
            return {"status": "CANCELLED", "message": "任务已停止。"}
        try:
            process = subprocess.Popen(args, cwd=candidate, env=_child_env(), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                       start_new_session=os.name != "nt")
        except OSError:
            return {"status": "FAIL", "message": "无法启动本地构建。"}
        _build_processes[run_id] = process
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_process_tree(process)
            process.communicate()
            return {"status": "FAIL", "message": "安装或构建超时。"}
        details = (stdout + "\n" + stderr)[-12000:]
        if process.returncode:
            return {"status": "FAIL", "message": "依赖安装或构建失败。", "details": details}
        return {"status": "PASS", "details": details}
    finally:
        with _build_lock:
            if _build_processes.get(run_id) is process:
                del _build_processes[run_id]


def build_candidate(run_id: str, files: list[dict[str, str]], candidate_name: str = "candidate") -> dict[str, Any]:
    settings = get_settings()
    if not (TEMPLATE / "pnpm-lock.yaml").is_file():
        return {"status": "FAIL", "message": "React 模板锁文件缺失。"}
    pnpm = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if not pnpm:
        return {"status": "FAIL", "message": "未找到 pnpm。"}
    if candidate_name not in {"candidate", "candidate-2"}:
        return {"status": "FAIL", "message": "候选名称无效。"}
    candidate = settings.runtime_dir / "runs" / run_id / candidate_name
    candidate.mkdir(parents=True, exist_ok=False)
    shutil.copytree(TEMPLATE, candidate, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", "dist"))
    with connect() as db:
        row = db.execute("SELECT set_id, revision FROM runs WHERE id=?", (run_id,)).fetchone()
    source_set = get_source_set(row["set_id"], row["revision"]) if row is not None else None
    if source_set:
        for reference in source_set["sources"]:
            item = get_input(reference["input_id"])
            if item and item["input_type"] == "figma_bundle":
                for asset in item["data"]["assets"]:
                    asset_name = asset["path"]
                    if not isinstance(asset_name, str) or not re.fullmatch(r"images/[^/\\:]+\.(?:png|jpg|jpeg)", asset_name, re.IGNORECASE):
                        return {"status": "FAIL", "message": "参考项目包含无效图片路径。"}
                    try:
                        content = base64.b64decode(asset["content_base64"], validate=True)
                    except (ValueError, binascii.Error, KeyError, TypeError):
                        return {"status": "FAIL", "message": "参考项目图片无法读取。"}
                    target = candidate / "public" / "images" / asset_name.split("/")[-1]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
    for item in files:
        target = candidate.joinpath(*item["path"].split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
    for args in ([pnpm, "install", "--frozen-lockfile", "--ignore-scripts", "--registry=https://registry.npmjs.org"],
                 [pnpm, "run", "build"]):
        outcome = _run_build_command(run_id, args, candidate, settings.build_timeout)
        if outcome["status"] != "PASS":
            return outcome
    if not (candidate / "dist" / "index.html").is_file():
        return {"status": "FAIL", "message": "构建未产生页面。"}
    return {"status": "PASS", "message": "React 工程已成功构建。"}


def preview_url(run_id: str, settings: Settings, candidate_name: str = "candidate") -> str:
    global _server
    if settings.preview_host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("预览仅支持本机地址。")
    if candidate_name not in {"candidate", "candidate-2"} or not re.fullmatch(r"run_[a-zA-Z0-9_-]+", run_id):
        raise RuntimeError("候选名称无效。")
    directory = settings.runtime_dir / "runs" / run_id / candidate_name / "dist"
    if not (directory / "index.html").is_file():
        raise RuntimeError("没有已构建的页面。")
    with _server_lock:
        if _server is None:
            for port in range(settings.preview_port_start, settings.preview_port_end + 1):
                try:
                    _server = LocalPreviewServer((settings.preview_host, port), PreviewHandler)
                    break
                except OSError:
                    continue
            if _server is None:
                raise RuntimeError("预览端口已被占用。")
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        return f"http://{settings.preview_host}:{_server.server_port}/{run_id}/{candidate_name}/"


def close_previews() -> None:
    global _server
    with _server_lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
            _server = None
