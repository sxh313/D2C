"""Versioned API for the local Design2Code workbench."""

import hashlib
import asyncio
import base64
import io
import json
import re
import shutil
import zipfile
from typing import Any, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from PIL import Image, ImageChops, ImageEnhance, ImageStat, UnidentifiedImageError

from design2code.inputs import import_figma, import_figma_bundle, import_figma_mcp, import_image, import_spec
from design2code.inspection import capture_reference_viewport
from design2code.runs import cancel_run, create_run, execute, execute_repair, read_run, request_repair
from design2code.runner import TEMPLATE, preview_url
from design2code.settings import get_settings
from design2code.storage import connect, get_input, get_source_set, identifier, json_encode, now

router = APIRouter(prefix="/api/d2c/v1")


@router.get("/figma/connection")
async def figma_connection() -> dict[str, Any]:
    """Check plugin presence only; never infer target-file ownership from it."""
    if get_settings().figma_mode != "mcp":
        return {"status": "not_mcp", "sessions": 0}
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.post("http://127.0.0.1:1994/rpc", json={"tool": "list_files"})
            response.raise_for_status()
            data = response.json()
        if (not isinstance(data, dict) or data.get("error")
                or not isinstance(data.get("data"), list)
                or not all(isinstance(session, dict) for session in data["data"])):
            return {"status": "unavailable", "sessions": 0}
        count = len(data["data"])
        return {"status": "connected" if count else "no_session", "sessions": count}
    except (httpx.HTTPError, ValueError):
        return {"status": "unavailable", "sessions": 0}


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


class SearchCheck(BaseModel):
    placeholder: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=100)
    visible_text: str = Field(min_length=1, max_length=150)
    hidden_text: str = Field(min_length=1, max_length=150)


class DialogCheck(BaseModel):
    open_button: str = Field(min_length=1, max_length=100)
    dialog_name: str = Field(min_length=1, max_length=100)
    close_button: str = Field(min_length=1, max_length=100)


class TabCheck(BaseModel):
    tab_name: str = Field(min_length=1, max_length=100)
    initial_text: str = Field(min_length=1, max_length=150)
    selected_text: str = Field(min_length=1, max_length=150)


class SourceSetRequest(BaseModel):
    sources: list[SourceReference] = Field(min_length=1, max_length=6)
    instructions: str = Field(default="", max_length=30_000)
    authority_by_dimension: dict[str, str] = Field(default_factory=dict)
    resolutions: list[dict[str, Any]] = Field(default_factory=lambda: [])
    search_check: SearchCheck | None = None
    dialog_check: DialogCheck | None = None
    tab_check: TabCheck | None = None


@router.post("/source-sets")
async def create_source_set(request: SourceSetRequest) -> dict[str, Any]:
    if request.tab_check:
        fields = request.tab_check.model_dump()
        if any(not value.strip() or value != value.strip() for value in fields.values()) or fields["initial_text"] == fields["selected_text"]:
            raise HTTPException(422, "标签页验收字段不能留空或包含首尾空格，两条内容必须不同。")
    if request.dialog_check and any(not value.strip() or value != value.strip() for value in request.dialog_check.model_dump().values()):
        raise HTTPException(422, "弹窗验收字段不能留空或包含首尾空格。")
    if request.search_check:
        fields = request.search_check.model_dump()
        if any(not value.strip() or value != value.strip() for value in fields.values()) or fields["visible_text"] == fields["hidden_text"]:
            raise HTTPException(422, "搜索验收的字段不能留空或包含首尾空格，两条示例文本必须不同。")
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


@router.get("/runs")
async def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List local task metadata without including prompts, files or credentials."""
    with connect() as db:
        rows = db.execute("SELECT id,status,calls,repairs,created_at,updated_at FROM runs WHERE status != 'DELETED' ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return {"runs": [{"run_id": row["id"], "status": row["status"], "model_requests": row["calls"],
                      "repairs": row["repairs"], "created_at": row["created_at"], "updated_at": row["updated_at"]} for row in rows]}


class DeleteHistoryRequest(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/runs/delete-history")
async def delete_history(request: DeleteHistoryRequest) -> dict[str, Any]:
    """Delete finished task records while retaining idempotency and local files."""
    ids = list(dict.fromkeys(request.run_ids))
    if any(not re.fullmatch(r"run_[a-f0-9]{32}", run_id) for run_id in ids):
        raise HTTPException(422, "任务 ID 格式无效。")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = [db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone() for run_id in ids]
        if any(row is None or row["status"] == "DELETED" for row in rows):
            raise HTTPException(404, "部分任务不存在或已删除，请刷新列表。")
        if any(row["status"] not in {"READY_FOR_REVIEW", "COMPLETE_LOCAL", "FAILED"} for row in rows if row):
            raise HTTPException(409, "只能删除已完成或失败的任务；运行中或结果未知的任务请保留。")
        for run_id in ids:
            db.execute("UPDATE runs SET status='DELETED', result_json=NULL, error=NULL, updated_at=? WHERE id=?", (now(), run_id))
            db.execute("DELETE FROM run_events WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM manual_reviews WHERE run_id=?", (run_id,))
    return {"deleted": ids}


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


def _has_built_candidate(run: dict[str, Any]) -> bool:
    result: dict[str, Any] = run.get("result") or {}
    checks: list[dict[str, Any]] = result.get("checks", [])
    return bool(result.get("files")) and any(
        check.get("id") == "build" and check.get("status") == "PASS"
        for check in checks
    )


def _can_preview(run: dict[str, Any]) -> bool:
    return run["status"] in {"READY_FOR_REVIEW", "COMPLETE_LOCAL"} or (
        run["status"] in {"FAILED", "UNKNOWN_EXTERNAL", "CANCELLED"} and _has_built_candidate(run)
    )


def _review_hash(source_hash: str, result: dict[str, Any]) -> str:
    snapshot: dict[str, Any] = {"source_hash": source_hash, "candidate_name": result.get("candidate_name", "candidate"), "files": result.get("files", [])}
    return hashlib.sha256(json_encode(snapshot).encode("utf-8")).hexdigest()


class ManualReviewRequest(BaseModel):
    candidate_hash: str = Field(min_length=64, max_length=64)
    visual: Literal["PASS", "FAIL", "NOT_REVIEWED"]
    interaction: Literal["PASS", "FAIL", "NOT_REVIEWED"]
    note: str = Field(default="", max_length=2000)


@router.get("/runs/{run_id}/manual-review")
async def get_manual_review(run_id: str, candidate: Literal["candidate", "candidate-2"] | None = None) -> dict[str, Any]:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    if not _has_built_candidate(run):
        raise HTTPException(409, "构建通过后才能记录人工复核。")
    if candidate is not None and candidate != (run["result"] or {}).get("candidate_name", "candidate"):
        raise HTTPException(409, "候选版本已变化，请刷新后重新复核。")
    candidate_hash = _review_hash(run["source_set_hash"], run["result"])
    with connect() as db:
        row = db.execute("SELECT data_json, created_at FROM manual_reviews WHERE run_id=? AND candidate_hash=?", (run_id, candidate_hash)).fetchone()
    return {"candidate_hash": candidate_hash, "review": {**json.loads(row["data_json"]), "created_at": row["created_at"]} if row else None}


@router.post("/runs/{run_id}/manual-review")
async def save_manual_review(run_id: str, request: ManualReviewRequest) -> dict[str, Any]:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT source_hash, status, result_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到该任务。")
        result: dict[str, Any] | None = json.loads(row["result_json"]) if row["result_json"] else None
        if row["status"] != "READY_FOR_REVIEW" or result is None or not _has_built_candidate({"result": result}):
            raise HTTPException(409, "当前任务不可复核，请等待构建完成。")
        candidate_hash = _review_hash(row["source_hash"], result)
        if candidate_hash != request.candidate_hash:
            raise HTTPException(409, "候选版本已变化，请刷新后重新复核。")
        review = {"visual": request.visual, "interaction": request.interaction, "note": request.note.strip()}
        timestamp = now()
        db.execute("INSERT OR REPLACE INTO manual_reviews (run_id,candidate_hash,data_json,created_at) VALUES (?,?,?,?)",
                   (run_id, candidate_hash, json_encode(review), timestamp))
    return {"candidate_hash": candidate_hash, "review": {**review, "created_at": timestamp}}


def _previous_built_run(run: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = run.get("result") or {}
    previous: dict[str, Any] = result.get("previous_candidate") or {}
    selected: dict[str, Any] = {**run, "result": previous}
    if run["status"] not in {"READY_FOR_REVIEW", "COMPLETE_LOCAL", "FAILED", "UNKNOWN_EXTERNAL", "CANCELLED"} or not _has_built_candidate(selected):
        raise HTTPException(409, "没有构建通过的修改前版本。")
    return selected


@router.get("/runs/{run_id}/preview")
async def get_preview(run_id: str, version: Literal["current", "previous"] = "current") -> dict[str, str]:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    if version == "previous":
        run = _previous_built_run(run)
    if not _can_preview(run):
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
async def inspection_image(run_id: str, viewport: Literal["desktop", "tablet", "mobile"], candidate: Literal["candidate", "candidate-2"] | None = None) -> FileResponse:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    current = (run["result"] or {}).get("candidate_name", "candidate")
    if current not in {"candidate", "candidate-2"}:
        raise HTTPException(404, "找不到检查截图。")
    if candidate is not None and candidate != current:
        raise HTTPException(409, "任务版本已变化，请刷新任务后重新查看截图。")
    path = get_settings().runtime_dir / "runs" / run_id / current / f"inspection-{viewport}.png"
    if not path.is_file():
        raise HTTPException(404, "该视口的检查截图未生成。")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


def _pixel_difference(reference: bytes, candidate_path: Any) -> dict[str, Any]:
    try:
        with Image.open(io.BytesIO(reference)) as ref, Image.open(candidate_path) as actual:
            if ref.size != actual.size:
                raise HTTPException(422, f"图片尺寸不同：参考图 {ref.width}×{ref.height}，页面截图 {actual.width}×{actual.height}；请使用相同尺寸的图片。")
            if ref.width * ref.height > 4_000_000:
                raise HTTPException(422, "图片超过 400 万像素，暂不支持像素差异图。")
            def flatten(image: Image.Image) -> Image.Image:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                return Image.alpha_composite(background, rgba).convert("RGB")
            diff = ImageChops.difference(flatten(ref), flatten(actual))
            mean = sum(ImageStat.Stat(diff).mean) / 3
            output = io.BytesIO()
            ImageEnhance.Brightness(diff).enhance(3).save(output, format="PNG")
            return {"width": ref.width, "height": ref.height, "mean_channel_difference": round(mean, 2),
                    "image_data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")}
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(422, "无法读取参考图或页面截图。") from exc


@router.get("/runs/{run_id}/visual-diff/{input_id}/{viewport}")
async def visual_diff(run_id: str, input_id: str, viewport: Literal["desktop", "tablet", "mobile", "reference"], candidate: Literal["candidate", "candidate-2"] | None = None) -> dict[str, Any]:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    source_set = get_source_set(run["source_set_id"], run["source_set_revision"])
    if source_set is None or not any(source["input_id"] == input_id for source in source_set["sources"]):
        raise HTTPException(404, "找不到任务参考图。")
    item = get_input(input_id)
    if not item or item["input_type"] not in {"screenshot", "figma"} or not item["data"].get("content_base64"):
        raise HTTPException(404, "找不到任务参考图。")
    current = (run["result"] or {}).get("candidate_name", "candidate")
    if current not in {"candidate", "candidate-2"}:
        raise HTTPException(404, "找不到检查截图。")
    if candidate is not None and candidate != current:
        raise HTTPException(409, "任务版本已变化，请刷新任务后重新比较。")
    reference = base64.b64decode(item["data"]["content_base64"])
    if viewport == "reference":
        if not _can_preview(run):
            raise HTTPException(409, "构建通过后才能重新截图。")
        try:
            with Image.open(io.BytesIO(reference)) as image:
                width, height = image.size
            if width > 2000 or height > 2000 or width * height > 4_000_000:
                raise HTTPException(422, "参考图宽高须各不超过 2000 像素，且不超过 400 万像素。")
            captured, warnings = await capture_reference_viewport(run_id, current, width, height)
            result = await asyncio.to_thread(_pixel_difference, reference, io.BytesIO(captured))
            result["capture"] = "reference_viewport"
            result["warnings"] = warnings
            result["candidate_image_data_url"] = "data:image/png;base64," + base64.b64encode(captured).decode("ascii")
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, "无法按参考图尺寸截取预览，请检查本地预览和 Chromium。") from exc
    path = get_settings().runtime_dir / "runs" / run_id / current / f"inspection-{viewport}.png"
    if not path.is_file():
        raise HTTPException(404, "该视口的检查截图未生成。")
    return await asyncio.to_thread(_pixel_difference, reference, path)


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str, version: Literal["current", "previous"] = "current") -> StreamingResponse:
    run = read_run(run_id)
    if run is None:
        raise HTTPException(404, "找不到该任务。")
    if version == "previous":
        run = _previous_built_run(run)
    if run["status"] not in {"READY_FOR_REVIEW", "COMPLETE_LOCAL", "FAILED"} and not (
        run["status"] in {"UNKNOWN_EXTERNAL", "CANCELLED"} and _has_built_candidate(run)
    ):
        raise HTTPException(409, "任务结束后才能导出。")
    candidate_name: str = str((run["result"] or {}).get("candidate_name", "candidate"))
    if candidate_name not in {"candidate", "candidate-2"}:
        raise HTTPException(409, "候选名称无效。")
    candidate = get_settings().runtime_dir / "runs" / run_id / candidate_name
    if not candidate.is_dir():
        raise HTTPException(409, "没有可导出的工程。")
    source_set = get_source_set(run["source_set_id"], run["source_set_revision"])
    candidate_hash = _review_hash(run["source_set_hash"], run["result"] or {})
    with connect() as db:
        review_row = db.execute("SELECT data_json, created_at FROM manual_reviews WHERE run_id=? AND candidate_hash=?", (run_id, candidate_hash)).fetchone()
    manual_review: dict[str, Any] | None = {**json.loads(review_row["data_json"]), "created_at": review_row["created_at"]} if review_row else None
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        has_readme = (candidate / "README.md").is_file() and not (candidate / "README.md").is_symlink()
        original_report = candidate / "report.json"
        if original_report.is_file() and not original_report.is_symlink():
            preserved = "report.generated.json"
            while (candidate / preserved).exists():
                preserved = "generated-" + preserved
            archive.write(original_report, f"design2code-page/{preserved}")
        for path in sorted(candidate.rglob("*")):
            rel = path.relative_to(candidate)
            if path.is_file() and not path.is_symlink() and not ({"node_modules", "dist", ".git"} & set(rel.parts)) and path.name != ".env" and rel.as_posix() != "report.json":
                archive.write(path, f"design2code-page/{rel.as_posix()}")
        if not has_readme:
            archive.writestr("design2code-page/README.md", "# Design2Code 页面\n\n使用 Node.js 和 pnpm，运行 `pnpm install --frozen-lockfile`，再运行 `pnpm dev`。\n")
        archive.writestr("design2code-page/report.json", json_encode({
            "run_id": run_id, "status": run["status"], "source_set_hash": run["source_set_hash"],
            "model_requests": run["model_requests"], "candidate_version": version, "candidate_name": candidate_name,
            "checks": (run["result"] or {}).get("checks", []),
            "candidate_review_hash": candidate_hash, "manual_review": manual_review,
            "cost_status": "UNKNOWN", "error": run["error"],
            "source_set": source_set,
        }))
    output.seek(0)
    return StreamingResponse(output, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})
