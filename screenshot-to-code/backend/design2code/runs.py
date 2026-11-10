"""Run state and the single-request model execution path."""

import asyncio
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, cast

from fastapi import HTTPException

from design2code.provider import ProviderError, generate
from design2code.inspection import inspect_candidate, inspect_interactions
from design2code.runner import build_candidate, cancel_build
from design2code.settings import get_settings
from design2code.storage import connect, get_source_set, identifier, json_encode, now


def _event(db: Any, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    row = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = ?", (run_id,)).fetchone()
    db.execute("INSERT INTO run_events VALUES (?, ?, ?, ?, ?)", (run_id, row[0], event_type, json_encode(payload), now()))


def recover_interrupted_runs() -> None:
    """Mark in-flight work interrupted by a server restart without retrying it."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id, status FROM runs WHERE status IN ('CREATED','GENERATING','REPAIRING','BUILDING')").fetchall()
        for row in rows:
            status = "UNKNOWN_EXTERNAL" if row["status"] in {"GENERATING", "REPAIRING"} else "FAILED"
            message = "服务重启，模型请求结果未知。" if status == "UNKNOWN_EXTERNAL" else "服务重启，任务执行中断。"
            db.execute("UPDATE runs SET status=?, error=?, updated_at=? WHERE id=?", (status, message, now(), row["id"]))
            _event(db, row["id"], status, {"status": status, "code": "SERVER_RESTART"})


def cancel_run(run_id: str) -> dict[str, Any]:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到该任务。")
        if row["status"] not in {"CREATED", "GENERATING", "REPAIRING", "BUILDING"}:
            raise HTTPException(409, "任务已结束。")
        status = "UNKNOWN_EXTERNAL" if row["status"] in {"GENERATING", "REPAIRING"} else "CANCELLED"
        message = "已停止等待；供应商请求可能仍在执行并产生费用。" if status == "UNKNOWN_EXTERNAL" else "已停止任务。"
        db.execute("UPDATE runs SET status=?, error=?, updated_at=? WHERE id=?", (status, message, now(), run_id))
        _event(db, run_id, status, {"status": status, "code": "USER_STOPPED"})
    if row["status"] == "BUILDING":
        cancel_build(run_id)
    return {"run_id": run_id, "status": status}


def _ensure_model_available(settings: Any) -> None:
    if not settings.model_ready:
        raise HTTPException(422, "模型配置不完整，请检查配置状态。")
    if settings.token_limit is not None or settings.cost_limit_micro_usd is not None:
        raise HTTPException(422, "已填写 token 或费用上限，但上限执行尚未接通。")


def create_run(set_id: str, revision: int, source_hash: str, key: str) -> tuple[dict[str, Any], bool]:
    settings = get_settings()
    _ensure_model_available(settings)
    request_hash = hashlib.sha256(json_encode({"set_id": set_id, "revision": revision, "hash": source_hash}).encode()).hexdigest()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id, request_hash FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "幂等键已用于另一项任务。")
            return {"run_id": existing["id"]}, False
        source_set = get_source_set(set_id, revision)
        if source_set is None or source_set["source_set_hash"] != source_hash:
            raise HTTPException(409, "资料集合不存在或已经变更。")
        confirmed = db.execute("SELECT 1 FROM source_confirmations WHERE set_id = ? AND revision = ? AND source_hash = ?",
                               (set_id, revision, source_hash)).fetchone()
        if not confirmed:
            raise HTTPException(409, "请先确认本次资料与指令。")
        if db.execute("SELECT 1 FROM runs WHERE status IN ('CREATED','GENERATING','BUILDING','REPAIRING')").fetchone():
            raise HTTPException(409, "已有任务正在运行。")
        run_id = identifier("run")
        timestamp = now()
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (run_id, set_id, revision, source_hash, key, request_hash, "CREATED", timestamp, timestamp))
        _event(db, run_id, "CREATED", {"status": "CREATED"})
    return {"run_id": run_id, "status": "CREATED"}, True


def read_run(run_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"]) if row["result_json"] else None
    return {"run_id": row["id"], "source_set_id": row["set_id"],
            "source_set_revision": row["revision"], "source_set_hash": row["source_hash"],
            "status": row["status"], "model_requests": row["calls"], "repairs": row["repairs"],
            "result": result, "error": row["error"], "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def parse_files(text: str) -> list[dict[str, str]]:
    try:
        result: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("GENERATION_INVALID", "模型输出不是有效的文件 JSON。") from exc
    if not isinstance(result, dict) or not isinstance(result.get("files"), list):
        raise ProviderError("GENERATION_INVALID", "模型没有返回文件列表。")
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in cast(list[Any], result["files"]):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
            raise ProviderError("GENERATION_INVALID", "生成的文件结构无效。")
        path = cast(str, item["path"])
        parts = PurePosixPath(path).parts
        allowed = path in {"src/App.tsx", "src/index.css"} or (path.startswith("src/components/") and path.endswith((".tsx", ".ts", ".css")))
        if not allowed or ".." in parts or "\\" in path or path in seen or len(item["content"]) > 300_000:
            raise ProviderError("GENERATION_INVALID", "生成结果包含不允许的文件路径、重复文件或过大文件。")
        seen.add(path)
        output.append({"path": path, "content": item["content"]})
    if len(output) > 40 or not {"src/App.tsx", "src/index.css"}.issubset(seen):
        raise ProviderError("GENERATION_INVALID", "生成结果缺少 App.tsx 或 index.css。")
    return output


async def execute(run_id: str) -> None:
    settings = get_settings()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["status"] != "CREATED" or row["calls"] >= settings.model_request_limit:
            return
        db.execute("UPDATE runs SET status = 'GENERATING', calls = calls + 1, updated_at = ? WHERE id = ?", (now(), run_id))
        _event(db, run_id, "GENERATING", {"status": "GENERATING", "model_request": row["calls"] + 1})
    source_set = get_source_set(row["set_id"], row["revision"])
    try:
        if source_set is None:
            raise ProviderError("INPUT_MISSING", "任务资料不存在。")
        text, usage = await generate(settings, source_set)
        try:
            files = parse_files(text)
        except ProviderError as exc:
            # Preserve a bounded response only when the provider returned text
            # but it was not a usable file set. Repair remains user initiated.
            invalid_result = {"files": [], "usage": usage, "cost": None, "cost_status": "UNKNOWN",
                              "invalid_output": text[:100_000], "build_details": str(exc),
                              "checks": [{"id": "build", "status": "NOT_RUN", "message": "生成内容无效，未执行构建。"},
                                         {"id": "visual", "status": "NOT_RUN", "message": "未执行视觉检查。"},
                                         {"id": "interactions", "status": "NOT_RUN", "message": "未执行交互检查。"}]}
            with connect() as db:
                changed = db.execute("UPDATE runs SET status='FAILED', result_json=?, error=?, updated_at=? WHERE id=? AND status='GENERATING'",
                                     (json_encode(invalid_result), str(exc), now(), run_id))
                if changed.rowcount:
                    _event(db, run_id, "FAILED", {"status": "FAILED", "code": exc.code, "message": str(exc)})
            return
        result: dict[str, Any] = {"files": files, "usage": usage, "cost": None, "cost_status": "UNKNOWN", "candidate_name": "candidate"}
        with connect() as db:
            changed = db.execute("UPDATE runs SET status = 'BUILDING', result_json = ?, updated_at = ? WHERE id = ? AND status = 'GENERATING'",
                       (json_encode(result), now(), run_id))
            if not changed.rowcount:
                return
            _event(db, run_id, "BUILDING", {"status": "BUILDING"})
        build = await asyncio.to_thread(build_candidate, run_id, files)
        result["checks"] = [
            {"id": "build", "status": build["status"], "message": build["message"]},
            {"id": "visual", "status": "NOT_RUN", "message": "视觉还原自动对比尚未执行。"},
            {"id": "interactions", "status": "NOT_RUN", "message": "交互尚未执行自动检查。"},
            {"id": "manual_review", "status": "MANUAL_REVIEW" if build["status"] == "PASS" else "NOT_RUN",
             "message": "请人工核对视觉还原与需求交互。" if build["status"] == "PASS" else "构建通过后才能人工核对页面。"},
        ]
        if build["status"] == "PASS":
            result["checks"].append(await inspect_candidate(run_id, "candidate"))
            result["checks"].append(await inspect_interactions(run_id, "candidate"))
        if build.get("details"):
            result["build_details"] = build["details"]
        final_status = "READY_FOR_REVIEW" if build["status"] == "PASS" else "FAILED"
        with connect() as db:
            changed = db.execute("UPDATE runs SET status = ?, result_json = ?, error = ?, updated_at = ? WHERE id = ? AND status = 'BUILDING'",
                       (final_status, json_encode(result), None if final_status == "READY_FOR_REVIEW" else build["message"], now(), run_id))
            if changed.rowcount:
                _event(db, run_id, final_status, {"status": final_status})
    except ProviderError as exc:
        status = "UNKNOWN_EXTERNAL" if exc.unknown else "FAILED"
        with connect() as db:
            changed = db.execute("UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ? AND status IN ('GENERATING','BUILDING')",
                       (status, str(exc), now(), run_id))
            if changed.rowcount:
                _event(db, run_id, status, {"status": status, "code": exc.code, "message": str(exc)})
    except Exception:
        # The request might have been sent. Do not silently retry after an unexpected failure.
        with connect() as db:
            current = db.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            interrupted_status = "UNKNOWN_EXTERNAL" if current and current["status"] == "GENERATING" else "FAILED"
            message = "执行中断，模型请求结果未知。" if interrupted_status == "UNKNOWN_EXTERNAL" else "本地构建执行中断。"
            changed = db.execute("UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ? AND status IN ('GENERATING','BUILDING')",
                       (interrupted_status, message, now(), run_id))
            if changed.rowcount:
                _event(db, run_id, interrupted_status, {"status": interrupted_status, "code": "EXECUTION_INTERRUPTED"})


def request_repair(run_id: str, instruction: str, key: str) -> bool:
    settings = get_settings()
    request_hash = hashlib.sha256(json_encode({"run_id": run_id, "instruction": instruction}).encode()).hexdigest()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT run_id, request_hash FROM repair_requests WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            if existing["run_id"] != run_id or existing["request_hash"] != request_hash:
                raise HTTPException(409, "幂等键已用于其他修复请求。")
            return False
        _ensure_model_available(settings)
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到该任务。")
        if row["status"] not in {"READY_FOR_REVIEW", "FAILED"} or not row["result_json"]:
            raise HTTPException(409, "当前任务没有可修复的候选。")
        if row["repairs"] >= settings.repair_limit or row["calls"] >= settings.model_request_limit:
            raise HTTPException(409, "本次任务的修复或模型请求次数已用完。")
        if db.execute("SELECT 1 FROM runs WHERE id != ? AND status IN ('CREATED','GENERATING','BUILDING','REPAIRING')", (run_id,)).fetchone():
            raise HTTPException(409, "已有其他任务正在运行。")
        db.execute("INSERT INTO repair_requests VALUES (?, ?, ?, ?)", (key, run_id, request_hash, now()))
        db.execute("UPDATE runs SET status = 'REPAIRING', calls = calls + 1, repairs = repairs + 1, error = NULL, updated_at = ? WHERE id = ?",
                   (now(), run_id))
        _event(db, run_id, "REPAIRING", {"status": "REPAIRING", "model_request": row["calls"] + 1})
    return True


async def execute_repair(run_id: str, instruction: str) -> None:
    # Claim before making any external request. A durable unique claim prevents
    # duplicate background executions, including across processes and restarts.
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["status"] != "REPAIRING" or not row["result_json"]:
            return
        claimed = db.execute("INSERT OR IGNORE INTO repair_execution_claims VALUES (?, ?)", (run_id, now()))
        if not claimed.rowcount:
            return
    try:
        original: dict[str, Any] = json.loads(row["result_json"])
        source_set = get_source_set(row["set_id"], row["revision"])
        if source_set is None:
            raise ProviderError("INPUT_MISSING", "任务资料不存在。")
        feedback = json_encode({"instruction": instruction, "files": original["files"],
                                "invalid_output": original.get("invalid_output", ""),
                                "build_details": original.get("build_details", "")})
        text, usage = await generate(get_settings(), source_set, repair_context=feedback)
        files = parse_files(text)
        with connect() as db:
            changed = db.execute("UPDATE runs SET status = 'BUILDING', updated_at = ? WHERE id = ? AND status = 'REPAIRING'", (now(), run_id))
            if not changed.rowcount:
                return
            _event(db, run_id, "BUILDING", {"status": "BUILDING", "purpose": "repair"})
        build = await asyncio.to_thread(build_candidate, run_id, files, "candidate-2")
        result: dict[str, Any] = {
            "files": files, "usage": usage, "cost": None, "cost_status": "UNKNOWN",
            "candidate_name": "candidate-2", "previous_candidate": original,
            "checks": [
                {"id": "build", "status": build["status"], "message": build["message"]},
                {"id": "visual", "status": "NOT_RUN", "message": "修复后的视觉自动对比尚未执行。"},
                {"id": "interactions", "status": "NOT_RUN", "message": "修复后的交互尚未执行检查。"},
                {"id": "manual_review", "status": "MANUAL_REVIEW" if build["status"] == "PASS" else "NOT_RUN",
                 "message": "请人工重新核对视觉还原与需求交互。" if build["status"] == "PASS" else "构建通过后才能人工核对页面。"},
            ],
        }
        if build["status"] == "PASS":
            result["checks"].append(await inspect_candidate(run_id, "candidate-2"))
            result["checks"].append(await inspect_interactions(run_id, "candidate-2"))
        if build.get("details"):
            result["build_details"] = build["details"]
        status = "READY_FOR_REVIEW" if build["status"] == "PASS" else "FAILED"
        with connect() as db:
            changed = db.execute("UPDATE runs SET status = ?, result_json = ?, error = ?, updated_at = ? WHERE id = ? AND status = 'BUILDING'",
                       (status, json_encode(result), None if status == "READY_FOR_REVIEW" else build["message"], now(), run_id))
            if changed.rowcount:
                _event(db, run_id, status, {"status": status, "purpose": "repair"})
    except ProviderError as exc:
        status = "UNKNOWN_EXTERNAL" if exc.unknown else "FAILED"
        with connect() as db:
            changed = db.execute("UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ? AND status IN ('REPAIRING','BUILDING')",
                       (status, str(exc), now(), run_id))
            if changed.rowcount:
                _event(db, run_id, status, {"status": status, "code": exc.code, "purpose": "repair"})
    except Exception:
        with connect() as db:
            current = db.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            status = "UNKNOWN_EXTERNAL" if current and current["status"] == "REPAIRING" else "FAILED"
            changed = db.execute("UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ? AND status IN ('REPAIRING','BUILDING')",
                       (status, "修复过程被中断。", now(), run_id))
            if changed.rowcount:
                _event(db, run_id, status, {"status": status, "code": "REPAIR_INTERRUPTED"})
