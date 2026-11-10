"""Import user design sources into immutable local snapshots."""

import base64
import binascii
import asyncio
import hashlib
import io
import json
import re
import shutil
import stat
import zipfile
import zlib
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from dotenv import dotenv_values

from design2code.settings import ENV_FILE, get_settings
from design2code.storage import connect, identifier, json_encode, now


def save_input(kind: str, data: dict[str, Any], digest: str) -> dict[str, Any]:
    input_id = identifier("inp")
    with connect() as db:
        db.execute("INSERT INTO inputs VALUES (?, ?, ?, ?, ?)",
                   (input_id, kind, digest, json_encode(data), now()))
    public_data = {k: v for k, v in data.items() if k not in {"content_base64", "node_data", "files", "assets"}}
    return {"input_id": input_id, "input_type": kind, "source_hash": digest,
            "status": "READY", "data": public_data}


def import_spec(content: str) -> dict[str, Any]:
    content = content.strip()
    if not content or len(content.encode("utf-8")) > 500_000:
        raise HTTPException(422, "Spec 不能为空且不能超过 500 KB。")
    return save_input("spec", {"text": content}, hashlib.sha256(content.encode("utf-8")).hexdigest())


def import_figma_bundle(encoded: str, name: str) -> dict[str, Any]:
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    if len(encoded) > 14_000_000:
        raise HTTPException(413, "项目包不能超过 10 MiB。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "项目包编码无效。") from exc
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "项目包不能超过 10 MiB。")
    files: list[dict[str, str]] = []
    assets: list[dict[str, str]] = []
    source_bytes = 0
    asset_bytes = 0
    seen: set[str] = set()
    asset_names: set[str] = set()
    ignored = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 250 or sum(entry.file_size for entry in entries) > 20 * 1024 * 1024:
                raise HTTPException(413, "项目包文件过多或展开后超过 20 MiB。")
            for entry in entries:
                path = entry.filename
                parts = PurePosixPath(path).parts
                mode = entry.external_attr >> 16
                if (not path or path.startswith("/") or "\\" in path or ":" in path or "\x00" in path
                        or any(part in {".", ".."} for part in path.split("/"))
                        or stat.S_ISLNK(mode) or entry.flag_bits & 1 or len(path) > 400):
                    raise HTTPException(422, "项目包包含不安全的路径、链接或加密文件。")
                key = path.rstrip("/").casefold()
                if key in seen:
                    raise HTTPException(422, "项目包含重复文件名。")
                seen.add(key)
                if entry.is_dir():
                    continue
                if entry.file_size > 2 * 1024 * 1024 or (entry.compress_size and entry.file_size > 250 * entry.compress_size):
                    raise HTTPException(413, "项目包中存在过大或压缩比例异常的文件。")
                ext = PurePosixPath(path).suffix.lower()
                if ext in {".html", ".tsx", ".jsx", ".css"} and not any(p.casefold() in {"node_modules", "dist", ".git"} for p in parts):
                    content = archive.read(entry)
                    source_bytes += len(content)
                    if source_bytes > 300_000:
                        raise HTTPException(413, "项目包可读取的源码超过 300 KB。")
                    try:
                        text = content.decode("utf-8-sig")
                    except UnicodeDecodeError as exc:
                        raise HTTPException(422, "项目源码必须使用 UTF-8 编码。") from exc
                    files.append({"path": path, "content": text})
                elif ext in {".png", ".jpg", ".jpeg"} and "images" in [p.casefold() for p in parts[:-1]]:
                    output_name = PurePosixPath(path).name
                    stem = output_name.split(".", 1)[0].upper()
                    if (not output_name or output_name[-1] in {" ", "."} or any(ord(c) < 32 or c in '<>"|?*' for c in output_name)
                            or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", stem)):
                        raise HTTPException(422, "项目包图片文件名不受支持。")
                    if output_name.casefold() in asset_names:
                        raise HTTPException(422, "项目包中的图片文件名重复。")
                    asset_names.add(output_name.casefold())
                    content = archive.read(entry)
                    asset_bytes += len(content)
                    if len(assets) >= 30 or asset_bytes > 5 * 1024 * 1024:
                        raise HTTPException(413, "项目包图片超过 30 张或合计超过 5 MiB。")
                    try:
                        with Image.open(io.BytesIO(content)) as image:
                            if image.format not in {"PNG", "JPEG"} or image.width * image.height > 40_000_000:
                                raise HTTPException(422, "项目包图片格式或尺寸不受支持。")
                            image.verify()
                    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
                        raise HTTPException(422, "项目包图片无法读取。") from exc
                    assets.append({"path": f"images/{output_name}", "content_base64": base64.b64encode(content).decode("ascii")})
                else:
                    ignored += 1
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, zlib.error, NotImplementedError) as exc:
        raise HTTPException(422, "项目包损坏或无法读取。") from exc
    if not files:
        raise HTTPException(422, "项目包中没有可读取的 HTML、React 或 CSS 文件。")
    paths = {item["path"] for item in files}
    kind = "vite" if "src/App.tsx" in paths else "nextjs" if "app/page.tsx" in paths else "html" if any(path.endswith("index.html") for path in paths) else "other"
    data: dict[str, Any] = {"name": name[:255], "format": kind, "file_count": len(files),
                            "asset_count": len(assets), "ignored_count": ignored,
                            "warning": "源码作为生成参考，包内依赖和脚本不会执行；需要另行提供参考截图以检查视觉。",
                            "files": files, "assets": assets}
    return save_input("figma_bundle", data, hashlib.sha256(raw).hexdigest())


def import_image(encoded: str, name: str) -> dict[str, Any]:
    if "," in encoded and encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    if len(encoded) > 14_000_000:
        raise HTTPException(413, "图片不能超过 10 MiB。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "图片编码无效。") from exc
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过 10 MiB。")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            image_format = image.format
            if image_format not in {"PNG", "JPEG"} or width * height > 40_000_000:
                raise HTTPException(422, "只支持不超过 4000 万像素的 PNG/JPEG 图片。")
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "无法读取图片。") from exc
    return save_input("screenshot", {
        "name": name[:255], "width": width, "height": height,
        "mime_type": "image/png" if image_format == "PNG" else "image/jpeg",
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }, hashlib.sha256(raw).hexdigest())


async def import_figma(url: str) -> dict[str, Any]:
    token = get_settings().figma_token
    if not token:
        raise HTTPException(422, "请先在根目录 .env 中填写 FIGMA_ACCESS_TOKEN 并重启后端。")
    file_key, node_id = _figma_link(url)
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.get(f"https://api.figma.com/v1/files/{file_key}/nodes",
                                        params={"ids": node_id}, headers={"X-Figma-Token": token})
            if response.status_code == 429:
                raise HTTPException(429, "Figma 读取达到限流，请稍后重试。")
            if response.status_code in {401, 403, 404}:
                raise HTTPException(422, "Figma 文件不可访问，请检查链接和访问权限。")
            response.raise_for_status()
            body = response.json()
            node = body.get("nodes", {}).get(node_id)
            if not node or not node.get("document"):
                raise HTTPException(422, "Figma 节点不存在或不可访问。")
            render_params = {"ids": node_id, "format": "png", "scale": "1"}
            if body.get("version"):
                render_params["version"] = str(body["version"])
            render = await client.get(f"https://api.figma.com/v1/images/{file_key}",
                                      params=render_params, headers={"X-Figma-Token": token})
            render.raise_for_status()
            image_url = render.json().get("images", {}).get(node_id)
            parsed_image = urlsplit(image_url or "")
            if parsed_image.scheme != "https" or not parsed_image.hostname:
                raise HTTPException(422, "无法获取 Figma 节点参考图。")
            chunks: list[bytes] = []
            total = 0
            async with client.stream("GET", image_url) as image_response:
                image_response.raise_for_status()
                async for chunk in image_response.aiter_bytes():
                    total += len(chunk)
                    if total > 10 * 1024 * 1024:
                        raise HTTPException(413, "Figma 节点参考图超过 10 MiB，请选择更小的节点。")
                    chunks.append(chunk)
            image_raw = b"".join(chunks)
            try:
                with Image.open(io.BytesIO(image_raw)) as reference:
                    if reference.format != "PNG" or reference.width * reference.height > 40_000_000:
                        raise HTTPException(422, "Figma 节点参考图格式或尺寸不受支持。")
                    reference.verify()
            except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
                raise HTTPException(422, "无法读取 Figma 节点参考图。") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Figma 读取失败，请检查网络。") from exc
    data: dict[str, Any] = {"file_key": file_key, "node_id": node_id, "version": body.get("version"),
            "name": node["document"].get("name", ""), "node_data": node["document"],
            "mime_type": "image/png", "content_base64": base64.b64encode(image_raw).decode("ascii")}
    return save_input("figma", data, hashlib.sha256(json_encode(data).encode("utf-8")).hexdigest())


def _figma_link(url: str) -> tuple[str, str]:
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise HTTPException(422, "请输入有效的 Figma 设计文件节点链接。") from exc
    path = parts.path.strip("/").split("/")
    if parts.scheme != "https" or parts.hostname not in {"figma.com", "www.figma.com"} or len(path) < 2 or path[0] not in {"design", "file"}:
        raise HTTPException(422, "请输入 Figma 设计文件中的节点链接。")
    file_key = path[1]
    node_id = unquote(parse_qs(parts.query).get("node-id", [""])[0]).replace("-", ":")
    if not file_key.isalnum() or not node_id or not all(c.isdigit() or c == ":" for c in node_id):
        raise HTTPException(422, "Figma 链接需要包含有效的节点标识。")
    return file_key, node_id


def _mcp_content(result: Any) -> Any:
    content = result.get("content", []) if isinstance(result, dict) else []
    for entry in content:
        if isinstance(entry, dict) and entry.get("type") == "text":
            try:
                return json.loads(str(entry.get("text", "")))
            except json.JSONDecodeError:
                return entry.get("text", "")
    return None


def _find_screenshot(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("base64"), str):
            return value
        for child in value.values():
            found = _find_screenshot(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_screenshot(child)
            if found:
                return found
    return None


def _mcp_error(result: Any) -> str | None:
    """Return a bounded tool error so bridge failures are actionable."""
    if not isinstance(result, dict) or not result.get("isError"):
        return None
    for entry in result.get("content", []):
        if isinstance(entry, dict) and entry.get("type") == "text":
            message = str(entry.get("text", "")).strip()
            if message:
                return message[:300]
    return "MCP 工具返回错误"


FIGMA_MCP_TIMEOUT_SECONDS = 90


async def import_figma_mcp(url: str) -> dict[str, Any]:
    settings = get_settings()
    if not hasattr(settings, "figma_bridge_client") and getattr(settings, "figma_token", ""):
        return await import_figma(url)
    file_key, node_id = _figma_link(url)
    node_script = settings.figma_bridge_client
    node = shutil.which("node")
    if not node or not node_script.is_file():
        raise HTTPException(503, "未找到 Figma MCP Bridge。请先构建 figma-mcp-bridge/server。")
    # Explicit binding is needed when the development plugin cannot read
    # figma.fileKey. Never infer a match from a filename or a single connection.
    config = dotenv_values(ENV_FILE, interpolate=False) if ENV_FILE.is_file() else {}
    bound_file = (config.get("D2C_FIGMA_MCP_BOUND_FILE_KEY") or "").strip()
    bound_session = (config.get("D2C_FIGMA_MCP_SESSION_KEY") or "").strip()
    session_key = bound_session if file_key == bound_file and bound_session.startswith("unsaved-") else ""
    try:
        process = await asyncio.create_subprocess_exec(
            node, str(node_script), file_key, node_id, session_key,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise HTTPException(503, "Figma MCP Bridge 无法启动，请检查 Node.js 和 bridge。") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=FIGMA_MCP_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        # Closing the client also closes its stdio connection; the bridge server
        # it spawned exits on stdin EOF. The persistent workbench bridge is separate.
        try:
            if process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(504, "Figma MCP Bridge 请求超时，请检查 Figma 插件连接。") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1000:]
        raise HTTPException(422, f"Figma MCP Bridge 未返回节点；请在 Figma Desktop 中打开 bridge 插件。{detail}")
    try:
        payload = json.loads(stdout.decode("utf-8"))
        bridge_errors = [_mcp_error(payload.get(key)) for key in ("node", "screenshot")]
        bridge_errors = [message for message in bridge_errors if message]
        if bridge_errors:
            if session_key and "No plugin connected for fileKey" in bridge_errors[0]:
                raise HTTPException(503, "Figma 插件会话已变化或断开。请确认目标文件已打开、Bridge 插件已连接，然后在项目目录重新运行 Bind-FigmaBridge.ps1 并提供该 Figma 链接。")
            raise HTTPException(503, f"Figma MCP Bridge 未连接或节点不可用：{bridge_errors[0]}")
        node_result = _mcp_content(payload.get("node"))
        screenshot_result = _mcp_content(payload.get("screenshot"))
        screenshot = _find_screenshot(screenshot_result)
        if not isinstance(node_result, dict) or not screenshot:
            raise ValueError("MCP 返回缺少节点或截图")
        image_raw = base64.b64decode(screenshot["base64"], validate=True)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(422, "Figma MCP 返回的数据无法解析。") from exc
    try:
        with Image.open(io.BytesIO(image_raw)) as reference:
            if reference.format != "PNG" or reference.width * reference.height > 40_000_000:
                raise HTTPException(422, "Figma MCP 节点参考图格式或尺寸不受支持。")
            reference.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Figma MCP 节点截图无法读取。") from exc
    data: dict[str, Any] = {"file_key": file_key, "node_id": node_id, "name": str(node_result.get("name", "")),
            "node_data": node_result, "mime_type": "image/png", "content_base64": base64.b64encode(image_raw).decode("ascii"),
            "source": "figma-mcp-bridge"}
    return save_input("figma", data, hashlib.sha256(json_encode(data).encode("utf-8")).hexdigest())
