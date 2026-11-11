"""Zero-dependency local Design2Code MVP.

This first runnable slice intentionally uses a deterministic local generator so
the product can be exercised without API keys. It is an integration seam for a
future screenshot/Figma/model adapter, not a claim of AI visual reconstruction.
"""

from __future__ import annotations

import html
import json
import re
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
MAX_BODY = 2 * 1024 * 1024


def text(value: object) -> str:
    return html.escape(str(value or "").strip())


def first_heading(spec: str) -> str:
    for line in spec.splitlines():
        value = re.sub(r"^\s*#+\s*", "", line).strip()
        if value:
            return value[:80]
    return "Design2Code 页面"


def list_items(spec: str) -> list[str]:
    items: list[str] = []
    for line in spec.splitlines():
        match = re.match(r"^\s*[-*]\s+(.+)$", line)
        if match:
            items.append(match.group(1).strip()[:120])
    return items[:8]


def generate_page(payload: dict) -> dict:
    input_type = payload.get("input_type", "spec")
    spec = str(payload.get("spec", "")).strip()
    image_name = str(payload.get("image_name", "")).strip()
    title = first_heading(spec) if spec else (Path(image_name).stem or "Design2Code 页面")
    items = list_items(spec) or ["主要内容区域", "可复用组件", "响应式布局"]
    safe_title = text(title)
    cards = "".join(
        f'<article class="card"><div class="card-index">0{index}</div>'
        f'<h3>{text(item)}</h3><p>这是一个可替换的内容模块，后续可由模型或人工完善。</p></article>'
        for index, item in enumerate(items, 1)
    )
    page = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; background:#f5f7fb; color:#182230; }}
* {{ box-sizing:border-box; }} body {{ margin:0; }} .shell {{ max-width:1120px; margin:0 auto; padding:56px 24px 72px; }}
.eyebrow {{ color:#5068d8; font-size:12px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
h1 {{ font-size:clamp(34px, 6vw, 68px); line-height:1.03; margin:14px 0 16px; max-width:760px; letter-spacing:-.04em; }}
.lead {{ color:#5b6676; font-size:18px; line-height:1.6; max-width:640px; }} .actions {{ display:flex; gap:12px; flex-wrap:wrap; margin:28px 0 52px; }}
button {{ border:0; border-radius:999px; padding:12px 18px; font:inherit; font-weight:700; cursor:pointer; background:#5068d8; color:white; }}
button.secondary {{ background:white; color:#5068d8; border:1px solid #d7dded; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
.card {{ background:white; border:1px solid #e2e7f0; border-radius:18px; padding:22px; min-height:170px; }} .card-index {{ color:#9aa6bb; font-size:12px; font-weight:700; }}
h3 {{ margin:30px 0 10px; font-size:20px; }} .card p {{ color:#6b7482; line-height:1.5; margin:0; }}
footer {{ color:#8490a1; font-size:13px; margin-top:44px; }}
@media (max-width:560px) {{ .shell {{ padding:36px 18px 50px; }} .lead {{ font-size:16px; }} }}
</style></head>
<body><main class="shell"><div class="eyebrow">Design2Code · {text(input_type)}</div>
<h1>{safe_title}</h1><p class="lead">这是一个无需 API Key 即可运行的本地生成预览。你可以先验证输入、生成、预览和导出流程，再接入真实模型。</p>
<div class="actions"><button onclick="alert('交互示例：后续可绑定真实动作')">开始体验</button><button class="secondary" onclick="document.querySelector('.grid').scrollIntoView({{behavior:'smooth'}})">查看模块</button></div>
<section class="grid">{cards}</section><footer>Generated locally · input: {text(input_type)}</footer></main></body></html>"""
    run_id = uuid.uuid4().hex[:12]
    checks = [
        {"id": "build-shape", "status": "PASS", "message": "生成结果包含可预览 HTML"},
        {"id": "responsive-baseline", "status": "PASS", "message": "已提供移动端基础媒体查询"},
        {"id": "visual-reference", "status": "NOT_RUN", "message": "本地 MVP 未执行真实视觉相似度评估"},
    ]
    files = [
        {"path": "index.html", "content": page},
        {"path": "README.generated.md", "content": f"# {title}\n\n本页面由 Design2Code 本地 MVP 生成。输入类型：{input_type}。\n"},
    ]
    return {"run_id": run_id, "input_type": input_type, "title": title, "files": files, "preview_html": page, "checks": checks}


class Handler(BaseHTTPRequestHandler):
    server_version = "Design2CodeMVP/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, data: dict, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json({"status": "ok", "mode": "local-deterministic", "model_calls": 0})
            return
        relative = "index.html" if path in ("/", "") else path.removeprefix("/")
        target = (WEB / relative).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "text/plain; charset=utf-8"
        raw = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/generate":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("request body must be between 1 byte and 2 MiB")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            result = generate_page(payload)
            self.send_json(result)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    port = 8787
    print(f"Design2Code running at http://127.0.0.1:{port}")
    print("Mode: local deterministic MVP; no model or external network calls")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
