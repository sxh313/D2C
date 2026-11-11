"""Local FigmaToCode conversion transport; never substitutes REST snapshots."""
import asyncio
import uuid
from typing import Any, cast

import httpx
from dotenv import dotenv_values
from fastapi import HTTPException

from design2code.inputs import _figma_link, import_figma_bundle
from design2code.settings import ENV_FILE

_conversion_lock = asyncio.Lock()
_MESSAGES = {
    "NO_SESSION": "没有目标文件的 Figma 插件会话。请运行新版 Bridge 插件，或改用 FigmaToCode 项目 ZIP。",
    "EMPTY_SELECTION": "请在 Figma 中选中要转换的画板。",
    "SELECTION_MISMATCH": "当前选区与节点链接不一致，请选中链接对应的画板。",
    "SELECT_ONE_FRAME": "请仅选中一个画板。",
    "BUSY": "已有 FigmaToCode 转换正在执行，请等待完成。",
    "TIMEOUT": "FigmaToCode 转换超时；不会自动重试，请检查插件。",
    "ASSET_FAILED": "FigmaToCode 图片导出失败，未创建可生成资料。",
    "CONVERSION_FAILED": "FigmaToCode 转换失败，未使用节点 JSON 或截图替代。",
    "PLUGIN_UPDATE_REQUIRED": "插件不支持真实转换，请重新构建并运行项目中的新版 Bridge 插件。",
    "BRIDGE_UNAVAILABLE": "本地 Figma Bridge 服务不可用，请先启动根目录服务。",
    "INVALID_RESULT": "插件转换结果不完整或与请求不匹配。",
}


def failure(code: str, request_id: str, status: int = 422) -> HTTPException:
    return HTTPException(status, {"code": code, "request_id": request_id,
                                 "status": "BLOCKED_EXTERNAL" if code in {
                                     "NO_SESSION", "BRIDGE_UNAVAILABLE", "PLUGIN_UPDATE_REQUIRED"} else "FAIL",
                                 "message": _MESSAGES[code]})


def classify_error(message: str) -> str:
    for code in ("EMPTY_SELECTION", "SELECTION_MISMATCH", "SELECT_ONE_FRAME", "BUSY", "ASSET_FAILED"):
        if code in message:
            return code
    if "Unknown request type" in message:
        return "PLUGIN_UPDATE_REQUIRED"
    if "No plugin connected" in message or "Plugin not connected" in message:
        return "NO_SESSION"
    if "timed out" in message.lower():
        return "TIMEOUT"
    return "CONVERSION_FAILED"


async def import_figma_conversion(url: str) -> dict[str, Any]:
    file_key, node_id = _figma_link(url)
    request_id = "d2c_" + uuid.uuid4().hex
    if _conversion_lock.locked():
        raise failure("BUSY", request_id, 409)
    config = dotenv_values(ENV_FILE, interpolate=False) if ENV_FILE.is_file() else {}
    bound_file = (config.get("D2C_FIGMA_MCP_BOUND_FILE_KEY") or "").strip()
    bound_session = (config.get("D2C_FIGMA_MCP_SESSION_KEY") or "").strip()
    session = bound_session if file_key == bound_file and bound_session.startswith("unsaved-") else file_key
    async with _conversion_lock:
        try:
            async with httpx.AsyncClient(timeout=190, trust_env=False) as client:
                response = await client.post("http://127.0.0.1:1994/rpc", json={
                    "tool": "d2c_convert_selection", "fileKey": session,
                    "params": {"request_id": request_id, "expectedNodeId": node_id, "outputFormat": "vite"},
                })
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise failure("TIMEOUT", request_id, 504) from exc
        except httpx.HTTPError as exc:
            raise failure("BRIDGE_UNAVAILABLE", request_id, 503) from exc
        except ValueError as exc:
            raise failure("INVALID_RESULT", request_id) from exc
        if not isinstance(payload, dict):
            raise failure("INVALID_RESULT", request_id)
        if payload.get("error"):
            code = classify_error(str(payload["error"]))
            raise failure(code, request_id, 503 if code == "NO_SESSION" else 422)
        raw_data: Any = cast(dict[str, Any], payload).get("data")
        data: dict[str, Any] = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
        if (not isinstance(data, dict) or data.get("kind") != "figma-to-code"
                or data.get("converter") != "FigmaToCode" or data.get("request_id") != request_id
                or data.get("nodeIds") != [node_id] or data.get("fileKey") != session
                or data.get("format") != "vite" or not isinstance(data.get("zipBase64"), str)
                or not isinstance(data.get("converterVersion"), str)
                or not isinstance(data.get("warnings"), list)
                or not all(isinstance(w, str) and len(w) <= 5000 for w in cast(list[Any], data["warnings"]))
                or len(data["warnings"]) > 500):
            raise failure("INVALID_RESULT", request_id)
        metadata: dict[str, Any] = {key: data.get(key) for key in
                    ("converterVersion", "request_id", "nodeIds", "nodeNames", "warnings")}
        metadata["fileKey"] = file_key
        return import_figma_bundle(data["zipBase64"], "figma-selection.zip", conversion=metadata)
