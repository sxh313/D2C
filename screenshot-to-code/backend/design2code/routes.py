"""Versioned API for the local Design2Code workbench."""

import hashlib
import asyncio
import io
import json
import shutil
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from design2code.inputs import import_figma, import_figma_bundle, import_figma_mcp, import_image, import_spec
from design2code.runs import cancel_run, create_run, execute, execute_repair, read_run, request_repair
from design2code.runner import TEMPLATE, preview_url
from design2code.settings import get_settings
from design2code.storage import connect, get_input, get_source_set, identifier, json_encode, now

router = APIRouter(prefix="/api/d2c/v1")


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    settings = get_settings()
    return {
        "provider_configured": settings.model_ready,
        "model": settings.model,
        "protocol": settings.protocol,
        "figma_mode": getattr(settings, "figma_mode", "rest"),
        "figma_configured": bool((getattr(settings, "figma_mode", "rest") == "mcp" and getattr(settings, "figma_bridge_client", None) and settings.figma_bridge_client.is_file()) or getattr(settings, "figma_token", "")),
        "token_limit_configured": settings.token_limit is not None,
        "cost_limit_configured": settings.cost_limit_micro_usd is not None,
        "model_request_limit": settings.model_request_limit,
        "repair_limit": settings.repair_limit,
        "configuration_issues": list(settings.issues),
        "generation_available": settings.model_ready and settings.token_limit is None
        and settings.cost_limit_micro_usd is None and (TEMPLATE / "pnpm-lock.yaml").is_file()
        and bool(shutil.which("pnpm.cmd") or shutil.which("pnpm")),
        "figma_import_available": bool((getattr(settings, "figma_mode", "rest") == "mcp" and getattr(settings, "figma_bridge_client", None) and settings.figma_bridge_client.is_file()) or getattr(settings, "figma_token", "")),
    }


class InputRequest(BaseModel):
    input_type: Literal["screenshot", "spec", "figma", "figma_bundle"]
    content: str = Field(max_length=14_000_000)
    name: str = "screenshot.png"


@router.post("/design-inputs")
async def create_input(request: InputRequest) -> dict[str, Any]:
    if request.input_type == "screenshot":
        return import_image(request.content, request.name)
    if request.input_type == "spec":
        return import_spec(request.content)
    if request.input_type == "figma_bundle":
        return import_figma_bundle(request.content, request.name)
    settings = get_settings()
    use_mcp = getattr(settings, "figma_mode", "rest") == "mcp" and hasattr(settings, "figma_bridge_client")
    return await import_figma_mcp(request.content) if use_mcp else await import_figma(request.content)


@router.get("/design-inputs/{input_id}")
async def read_input(input_id: str) -> dict[str, Any]:
    item = get_input(input_id)
    if item is None:
        raise HTTPException(404, "找不到该资料。")
    data = {k: v for k, v in item["data"].items() if k not in {"content_base64", "node_data", "files", "assets"}}
    return {**item, "data": data, "status": "READY"}


class SourceReference(BaseModel):
    input_id: str
    role: str = Field(default="reference", max_length=100)
    scope: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class SourceSetRequest(BaseModel):
    sources: list[SourceReference] = Field(min_length=1, max_length=6)
    instructions: str = Field(default="", max_length=30_000)
    authority_by_dimension: dict[str, str] = Field(default_factory=dict)
    resolutions: list[dict[str, Any]] = Field(default_factory=lambda: [])


@router.post("/source-sets")
async def create_source_set(request: SourceSetRequest) -> dict[str, Any]:
    ids = [source.input_id for source in request.sources]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "同一份资料不能重复添加。")
    inputs = [get_input(input_id) for input_id in ids]
    if any(item is None for item in inputs):
        raise HTTPException(404, "部分资料不存在，请重新添加。")
    kinds = [item["input_type"] for item in inputs if item is not None]
    if kinds.count("screenshot") > 3 or kinds.count("spec") > 1 or kinds.count("figma") > 1 or kinds.count("figma_bundle") > 1:
        raise HTTPException(422, "最多添加 3 张图片、1 份 Spec、1 个 Figma 节点和 1 个项目包。")
    if any(value not in ids and value != "instructions" for value in request.authority_by_dimension.values()):
        raise HTTPException(422, "来源规则引用了未加入的资料。")
    sources = []
    for ref, item in zip(request.sources, inputs):
        assert item is not None
        sources.append({**ref.model_dump(), "input_type": item["input_type"], "source_hash": item["source_hash"]})
    data: dict[str, Any] = {**request.model_dump(), "sources": sources, "confirmed": False}
    digest = hashlib.sha256(json_encode(data).encode("utf-8")).hexdigest()
    set_id = identifier("srcset")
    with connect() as db:
        db.execute("INSERT INTO source_sets VALUES (?, ?, ?, ?, ?)", (set_id, 1, digest, json_encode(data), now()))
    return {"source_set_id": set_id, "source_set_revision": 1, "source_set_hash": digest, **data}


@router.get("/source-sets/{set_id}")
async def read_source_set(set_id: str) -> dict[str, Any]:
    result = get_source_set(set_id)
    if result is None:
        raise HTTPException(404, "找不到资料集合。")
    return result


class ConfirmRequest(BaseModel):
    source_set_revision: int
    source_set_hash: str


@router.post("/source-sets/{set_id}/confirm")
async def confirm_source_set(set_id: str, request: ConfirmRequest) -> dict[str, Any]:
    source_set = get_source_set(set_id, request.source_set_revision)
    if source_set is None or source_set["source_set_hash"] != request.source_set_hash:
        raise HTTPException(409, "资料集合不存在或已经变更。")
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO source_confirmations VALUES (?, ?, ?, ?)",
                   (set_id, request.source_set_revision, request.source_set_hash, now()))
    return {"source_set_id": set_id, "source_set_revision": request.source_set_revision,
            "source_set_hash": request.source_set_hash, "confirmed": True}


class RunRequest(ConfirmRequest):
    source_set_id: str


class RepairRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=5000)


@router.post("/runs", status_code=202)
async def start_run(request: RunRequest, background: BackgroundTasks,
                    idempotency_key: str = Header(min_length=8, max_length=128)) -> dict[str, Any]:
    result, created = create_run(request.source_set_id, request.source_set_revision,
                                 request.source_set_hash, idempotency_key)
    if created:
        background.add_task(execute, result["run_id"])
    return result


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    result = read_run(run_id)
    if result is None:
        raise HTTPException(404, "找不到该任务。")
    return result


@router.post("/runs/{run_id}/cancel")
async def stop_run(run_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(cancel_run, run_id)


@router.post("/runs/{run_id}/repair", status_code=202)
async def repair_run(run_id: str, request: RepairRequest, background: BackgroundTasks,
                     idempotency_key: str = Header(min_length=8, max_length=128)) -> dict[str, Any]:
    instruction = request.instruction.strip()
    if not instruction:
        raise HTTPException(422, "请填写修改要求。")
    created = request_repair(run_id, instruction, idempotency_key)
    if created:
        background.add_task(execute_repair, run_id, instruction)
    return {"run_id": run_id, "accepted": True}


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, after_seq: int = 0) -> dict[str, Any]:
    if read_run(run_id) is None:
        raise HTTPException(404, "找不到该任务。")
    with connect() as db:
        rows = db.execute("SELECT seq,type,payload_json,created_at FROM run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500",
                          (run_id, max(0, after_seq))).fetchall()
    return {"events": [{"seq": row["seq"], "type": row["type"], "payload": json.loads(row["payload_json"]),
                         "created_at": row["created_at"]} for row in rows]}


@router.get("/runs/{run_id}/preview")
async def get_preview(run_id: str) -> dict[str, str]:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    if run["status"] not in {"READY_FOR_REVIEW", "COMPLETE_LOCAL"}:
        raise HTTPException(409, "构建通过后才能预览。")
    try:
        return {"url": preview_url(run_id, get_settings(), (run["result"] or {}).get("candidate_name", "candidate"))}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/runs/{run_id}/visual-references")
async def visual_references(run_id: str) -> dict[str, Any]:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    source_set = get_source_set(run["source_set_id"], run["source_set_revision"])
    if source_set is None:
        raise HTTPException(404, "找不到任务资料。")
    references = []
    for source in source_set["sources"]:
        item = get_input(source["input_id"])
        if item and item["input_type"] in {"screenshot", "figma"} and item["data"].get("content_base64"):
            references.append({"id": item["input_id"], "type": item["input_type"],
                               "name": item["data"].get("name") or item["input_type"],
                               "data_url": f'data:{item["data"]["mime_type"]};base64,{item["data"]["content_base64"]}'})
    return {"references": references}


@router.get("/runs/{run_id}/inspection-image/{viewport}")
async def inspection_image(run_id: str, viewport: Literal["desktop", "mobile"]) -> FileResponse:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    candidate = (run["result"] or {}).get("candidate_name", "candidate")
    if candidate not in {"candidate", "candidate-2"}:
        raise HTTPException(404, "找不到检查截图。")
    path = get_settings().runtime_dir / "runs" / run_id / candidate / f"inspection-{viewport}.png"
    if not path.is_file():
        raise HTTPException(404, "该视口的检查截图未生成。")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str) -> StreamingResponse:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    if run["status"] not in {"READY_FOR_REVIEW", "COMPLETE_LOCAL", "FAILED"}:
        raise HTTPException(409, "任务结束后才能导出。")
    candidate_name: str = str((run["result"] or {}).get("candidate_name", "candidate"))
    if candidate_name not in {"candidate", "candidate-2"}:
        raise HTTPException(409, "候选名称无效。")
    candidate = get_settings().runtime_dir / "runs" / run_id / candidate_name
    if not candidate.is_dir():
        raise HTTPException(409, "没有可导出的工程。")
    source_set = get_source_set(run["source_set_id"], run["source_set_revision"])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(candidate.rglob("*")):
            rel = path.relative_to(candidate)
            if path.is_file() and not path.is_symlink() and not ({"node_modules", "dist", ".git"} & set(rel.parts)) and path.name != ".env":
                archive.write(path, f"design2code-page/{rel.as_posix()}")
        archive.writestr("design2code-page/README.md", "# Design2Code 页面\n\n使用 Node.js 和 pnpm，运行 `pnpm install --frozen-lockfile`，再运行 `pnpm dev`。\n")
        archive.writestr("design2code-page/report.json", json_encode({
            "run_id": run_id, "status": run["status"], "source_set_hash": run["source_set_hash"],
            "model_requests": run["model_requests"], "checks": (run["result"] or {}).get("checks", []),
            "cost_status": "UNKNOWN", "error": run["error"],
            "source_set": source_set,
        }))
    output.seek(0)
    return StreamingResponse(output, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})
