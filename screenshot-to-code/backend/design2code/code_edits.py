"""Durable manual source revision, sharing the Run's single repair slot."""
import asyncio
import hashlib
import json
from typing import Any

from fastapi import HTTPException

from design2code.figma_project import figma_seed, project_lineage
from design2code.inspection import inspect_candidate, inspect_dialog, inspect_interactions, inspect_search, inspect_tab
from design2code.provider import ProviderError
from design2code.runner import build_candidate
from design2code.runs import _event, _pending_build_checks, parse_files
from design2code.settings import get_settings
from design2code.storage import connect, get_source_set, json_encode, now


def candidate_hash(source_hash: str, result: dict[str, Any]) -> str:
    snapshot: dict[str, Any] = {"source_hash": source_hash, "candidate_name": result.get("candidate_name", "candidate"),
                "files": result.get("files", [])}
    return hashlib.sha256(json_encode(snapshot).encode("utf-8")).hexdigest()


def request_code_edit(run_id: str, base_hash: str, files: list[dict[str, str]], key: str) -> bool:
    try:
        files = parse_files(json_encode({"files": files}))
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from exc
    request_hash = hashlib.sha256(json_encode({"mode": "manual", "run_id": run_id,
        "base_hash": base_hash, "files": files}).encode()).hexdigest()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT run_id,request_hash FROM repair_requests WHERE idempotency_key=?", (key,)).fetchone()
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] == "DELETED":
            raise HTTPException(404, "找不到该任务。")
        if prior:
            if prior["run_id"] != run_id or prior["request_hash"] != request_hash:
                raise HTTPException(409, "幂等键已用于其他修改。")
            return False
        if row["status"] not in {"READY_FOR_REVIEW", "FAILED"} or not row["result_json"]:
            raise HTTPException(409, "当前任务没有可编辑的候选。")
        if row["repairs"] >= get_settings().repair_limit:
            raise HTTPException(409, "本次任务的一次修改额度已用完。")
        original: dict[str, Any] = json.loads(row["result_json"])
        if candidate_hash(row["source_hash"], original) != base_hash:
            raise HTTPException(409, "候选已经变更，请重新读取源码。")
        before = {item["path"]: item["content"] for item in original.get("files", [])}
        after = {item["path"]: item["content"] for item in files}
        if before.keys() != after.keys():
            raise HTTPException(422, "请保留当前候选的全部文件，只修改文件内容。")
        changed = sorted(path for path in after if after[path] != before[path])
        if not changed:
            raise HTTPException(422, "源码没有变化。")
        if db.execute("SELECT 1 FROM runs WHERE status IN ('CREATED','GENERATING','BUILDING','REPAIRING')").fetchone():
            raise HTTPException(409, "已有任务正在运行。")
        source = get_source_set(row["set_id"], row["revision"])
        if source is None:
            raise HTTPException(409, "任务资料不存在。")
        seed = figma_seed(source)
        project = project_lineage(seed, after, operations=changed, mode="manual_project_edit") if seed else None
        result: dict[str, Any] = {"files": files, "candidate_name": "candidate-2", "previous_candidate": original,
                  "engine": "manual-code-edit", "tools": [], "model": None,
                  "origin": {name: original.get(name) for name in ("engine", "engine_version", "model", "agent_run_id")},
                  "project": project, "usage": {"model_requests": 0, "engine": "manual-code-edit"},
                  "cost": None, "cost_status": "NOT_APPLICABLE",
                  "revision": {"kind": "manual", "base_candidate_hash": base_hash, "changed_files": changed},
                  "checks": _pending_build_checks(source, repaired=True)}
        db.execute("INSERT INTO repair_requests VALUES (?,?,?,?)", (key, run_id, request_hash, now()))
        db.execute("UPDATE runs SET status='BUILDING',repairs=repairs+1,result_json=?,error=NULL,updated_at=? WHERE id=?",
                   (json_encode(result), now(), run_id))
        _event(db, run_id, "BUILDING", {"status": "BUILDING", "purpose": "manual_code_edit", "files": changed,
                                        "model_requests": 0})
    return True


async def execute_code_edit(run_id: str) -> None:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "BUILDING" or not row["result_json"]:
            return
        result: dict[str, Any] = json.loads(row["result_json"])
        if result.get("revision", {}).get("kind") != "manual":
            return
        if not db.execute("INSERT OR IGNORE INTO repair_execution_claims VALUES (?,?)", (run_id, now())).rowcount:
            return
    try:
        source = get_source_set(row["set_id"], row["revision"])
        if source is None:
            raise ValueError("source missing")
        build = await asyncio.to_thread(build_candidate, run_id, result["files"], "candidate-2")
        result["checks"][0] = {"id": "build", "status": build["status"], "message": build["message"]}
        result["checks"][3] = {"id": "manual_review", "status": "MANUAL_REVIEW" if build["status"] == "PASS" else "NOT_RUN",
                                "message": "请重新核对手写修改后的页面。" if build["status"] == "PASS" else "构建未通过，保留修改前版本。"}
        if build.get("details"):
            result["build_details"] = build["details"]
        if build["status"] == "PASS":
            result["checks"].extend([await inspect_candidate(run_id, "candidate-2"), await inspect_interactions(run_id, "candidate-2")])
            for field, inspect in (("search_check", inspect_search), ("dialog_check", inspect_dialog), ("tab_check", inspect_tab)):
                if source.get(field):
                    check = await inspect(run_id, "candidate-2", source[field])
                    result["checks"] = [item for item in result["checks"] if item["id"] != check["id"]] + [check]
        status = "READY_FOR_REVIEW" if build["status"] == "PASS" else "FAILED"
        error = None if status == "READY_FOR_REVIEW" else build["message"]
    except Exception:
        status, error = "FAILED", "手写源码构建或检查中断；已保存源码和修改前版本。"
    with connect() as db:
        updated = db.execute("UPDATE runs SET status=?,result_json=?,error=?,updated_at=? WHERE id=? AND status='BUILDING'",
                             (status, json_encode(result), error, now(), run_id))
        if updated.rowcount:
            _event(db, run_id, status, {"status": status, "purpose": "manual_code_edit"})
