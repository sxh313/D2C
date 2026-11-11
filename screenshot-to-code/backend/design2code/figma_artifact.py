"""Content-addressed manifests shared by ZIP import and plugin conversion.

The manifest deliberately does not assert that an arbitrary uploaded ZIP was
produced by FigmaToCode. Plugin execution and user-declared origin are distinct.
"""
import base64
import hashlib
from typing import Any
from urllib.parse import quote

from design2code.storage import json_encode


def digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def create_artifact(data: dict[str, Any], raw: bytes,
                    conversion: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = conversion or {}
    files: list[dict[str, Any]] = [{"path": entry["path"],
              "content_hash": digest_bytes(entry["content"].encode("utf-8")),
              "bytes": len(entry["content"].encode("utf-8"))} for entry in data["files"]]
    assets: list[dict[str, Any]] = [{"path": "public/" + entry["path"],
               "source_path": entry.get("source_path", entry["path"]),
               "url": "./" + quote(entry["path"], safe="/"),
               "content_hash": digest_bytes(base64.b64decode(entry["content_base64"], validate=True))}
              for entry in data["assets"]]
    warnings = list(metadata.get("warnings", []))
    if not conversion:
        warnings.append("上传包来源由用户声明，无法仅根据 ZIP 验证转换器版本；未补造节点或转换记录。")
    if data["ignored_count"]:
        warnings.append(f"未载入 {data['ignored_count']} 个配置、说明或不支持文件；包内脚本不会执行。")
    manifest: dict[str, Any] = {
        "schema_version": 1, "kind": "figma-to-code", "converter": "FigmaToCode",
        "converter_version": metadata.get("converterVersion"),
        "provenance": "plugin_execution" if conversion else "user_declared",
        "transport": "desktop_bridge" if conversion else "plugin_zip",
        "source": {"zip_hash": digest_bytes(raw), "file_key": metadata.get("fileKey"),
                   "node_ids": metadata.get("nodeIds", []), "node_names": metadata.get("nodeNames", [])},
        "request_id": metadata.get("request_id"),
        "format": data["format"], "files": files, "assets": assets, "warnings": warnings,
    }
    manifest["artifact_hash"] = digest_bytes(json_encode(manifest).encode("utf-8"))
    return manifest
