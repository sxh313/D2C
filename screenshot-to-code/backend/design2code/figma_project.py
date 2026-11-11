"""Turn a real Vite conversion into editable source, preserving provenance."""
import re
from typing import Any

from agent.project import is_project_file, normalize_project_source
from design2code.figma_artifact import digest_bytes
from design2code.storage import get_input


def figma_seed(source_set: dict[str, Any]) -> dict[str, Any] | None:
    for reference in source_set["sources"]:
        item = get_input(reference["input_id"])
        if item and item["input_type"] == "figma_bundle" and item["data"]["format"] == "vite":
            data = item["data"]
            files: dict[str, str] = {}
            source_paths: dict[str, str] = {}
            for entry in data["files"]:
                path, content = entry["path"], entry["content"]
                if not is_project_file(path):
                    continue
                if path.endswith(".css") and re.search(r"@import\s+[\"']tailwindcss[\"']", content):
                    raise ValueError("项目使用 Tailwind 4，当前受控构建模板为 Tailwind 3。请从插件导出 HTML/JSX Vite 项目；原始包已保留。")
                content = normalize_project_source(path, content)
                source_paths[path] = path
                files[path] = content
            if "src/App.tsx" not in files:
                raise ValueError("FigmaToCode Vite 项目缺少可运行的 src/App.tsx。")
            missing_css = "src/index.css" not in files
            # The upstream absolute-layout root uses height:100%. Its generated
            # <main> needs a definite viewport-height chain in the trusted shell.
            files.setdefault("src/index.css", "html, body, #root { margin: 0; min-height: 100%; height: 100%; }\n#root > main { min-height: 100%; height: 100%; }\n")
            return {"input_id": item["input_id"], "artifact_hash": data.get("artifact", {}).get("artifact_hash"),
                    "converter_version": data.get("artifact", {}).get("converter_version"),
                    "files": files, "source_paths": source_paths,
                    "warnings": ["沿用转换源码和资源；依赖、入口及构建配置采用受控 React/Vite 模板，原包保持不变。"]
                    + (["原包缺少 index.css：补齐视口高度链，防止百分比高度容器坍塌；原转换布局和图片尺寸保留，响应式效果需单独检查。"] if missing_css else [])}
    return None


def is_conversion_only(source_set: dict[str, Any]) -> bool:
    sources = source_set.get("sources", [])
    if len(sources) != 1 or source_set.get("instructions", "").strip():
        return False
    item = get_input(sources[0]["input_id"])
    return bool(item and item["input_type"] == "figma_bundle" and item["data"]["format"] == "vite")


def project_lineage(seed: dict[str, Any], files: dict[str, str], *, operations: list[str],
                    mode: str) -> dict[str, Any]:
    baseline: dict[str, str] = seed["files"]
    return {"mode": mode, "input_id": seed["input_id"], "artifact_hash": seed["artifact_hash"],
            "content_hash_basis": "utf8_source_text",
            "warnings": seed["warnings"], "operations": operations,
            "files": [{"path": path, "source_path": seed["source_paths"].get(path),
                       "base_hash": digest_bytes(baseline[path].encode()) if path in baseline else None,
                       "content_hash": digest_bytes(content.encode()),
                       "baseline_kind": "converted_source" if path in seed["source_paths"] else "template_default",
                       "change": "added" if path not in seed["source_paths"] else "unchanged" if content == baseline[path] else "modified"}
                      for path, content in sorted(files.items())]}
