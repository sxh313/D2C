"""Exercise combined inputs through the actual local API without model calls."""

import base64
import asyncio
import io
import functools
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pytest import MonkeyPatch
from playwright.async_api import Error as PlaywrightError, async_playwright

from design2code.routes import router
from design2code.routes import _pixel_difference
import design2code.storage as storage
import design2code.runs as runs
import design2code.inputs as inputs
import design2code.provider as provider
import design2code.runner as runner
import design2code.inspection as inspection
import design2code.routes as d2c_routes
import design2code.settings as d2c_settings


def test_generated_jsx_root_image_src_uses_relative_path() -> None:
    payload = {"files": [
        {"path": "src/App.tsx", "content": "<><img src=\"/images/a.png\" /><img src=\"https://example.test/a.png\" /></>"},
        {"path": "src/index.css", "content": "body { color: black; }"},
    ]}
    files = runs.parse_files(json.dumps(payload))
    assert 'src="./images/a.png"' in files[0]["content"]
    assert 'src="https://example.test/a.png"' in files[0]["content"]
    assert files[1]["content"] == payload["files"][1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, expected", [({"data": [{}]}, "connected"), ({"data": []}, "no_session"), ({"error": "failed"}, "unavailable")])
async def test_figma_connection_status(monkeypatch: MonkeyPatch, payload: dict[str, Any], expected: str) -> None:
    monkeypatch.setattr(d2c_routes, "get_settings", lambda: SimpleNamespace(figma_mode="mcp"))
    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None: pass
        async def __aenter__(self) -> "FakeClient": return self
        async def __aexit__(self, *_args: Any) -> None: pass
        async def post(self, *_args: Any, **_kwargs: Any) -> Any:
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(d2c_routes.httpx, "AsyncClient", FakeClient)
    assert (await d2c_routes.figma_connection())["status"] == expected


def test_recent_runs_returns_bounded_metadata_only(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    with storage.connect() as db:
        for index in range(2):
            db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (f"run_{index}", "set", 1, "hash", f"key_{index}", "hash", "FAILED", '{"private":"not listed"}', f"2026-01-0{index + 1}", storage.now()))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    result = client.get("/api/d2c/v1/runs?limit=1")
    assert result.status_code == 200
    assert len(result.json()["runs"]) == 1 and result.json()["runs"][0]["run_id"] == "run_1"
    assert "not listed" not in result.text
    assert client.get("/api/d2c/v1/runs?limit=101").status_code == 422


@pytest.mark.parametrize("status", ["FAILED", "UNKNOWN_EXTERNAL", "CANCELLED"])
def test_interrupted_repair_keeps_built_candidate_accessible(status: str, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    candidate = tmp_path / "runs" / "run_test" / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "package.json").write_text("{}", encoding="utf-8")
    run = {"status": status, "result": {"candidate_name": "candidate", "files": [{"path": "src/App.tsx", "content": "app"}],
                                       "checks": [{"id": "build", "status": "PASS"}]},
           "source_set_id": "set", "source_set_revision": 1, "source_set_hash": "hash",
           "model_requests": 2, "error": "修改中断"}
    monkeypatch.setattr(d2c_routes, "read_run", lambda _id: run)
    monkeypatch.setattr(d2c_routes, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(d2c_routes, "get_source_set", lambda *_args: {"sources": []})
    monkeypatch.setattr(d2c_routes, "preview_url", lambda *_args: "/previous/")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/d2c/v1/runs/run_test/preview").json() == {"url": "/previous/"}
    exported = client.get("/api/d2c/v1/runs/run_test/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        report = json.loads(archive.read("design2code-page/report.json"))
        assert report["status"] == status and report["error"] == "修改中断"
    run["result"]["checks"][0]["status"] = "FAIL"
    assert client.get("/api/d2c/v1/runs/run_test/preview").status_code == 409
    if status != "FAILED":
        assert client.get("/api/d2c/v1/runs/run_test/export").status_code == 409


@pytest.mark.parametrize("override", ["D2C_MODEL_REQUEST_LIMIT=3", "D2C_REPAIR_LIMIT=2", "D2C_AUTO_RETRY_LIMIT=1", "D2C_MODEL_REQUEST_LIMIT=-1"])
def test_unsafe_request_settings_block_model(tmp_path: Path, monkeypatch: MonkeyPatch, override: str) -> None:
    env = tmp_path / ".env"
    env.write_text("D2C_PROVIDER=openai\nD2C_API_PROTOCOL=openai_responses\nOPENAI_BASE_URL=https://example.invalid/v1\nOPENAI_API_KEY=test-only\nD2C_MODEL=openai/gpt-6-luna\n" + override + "\n", encoding="utf-8")
    monkeypatch.setattr(d2c_settings, "ENV_FILE", env)
    d2c_settings.get_settings.cache_clear()
    try:
        settings = d2c_settings.get_settings()
        assert not settings.model_ready
        with pytest.raises(HTTPException) as exc:
            runs._ensure_model_available(settings)
        assert exc.value.status_code == 422
    finally:
        d2c_settings.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_duplicate_initial_execution_calls_model_once(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_request_limit=2))
    monkeypatch.setattr(runs, "get_source_set", lambda *_args: {})
    monkeypatch.setattr(runs, "build_candidate", lambda *_args: {"status": "FAIL", "message": "simulated build"})
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def fake_generate(_settings: Any, _source_set: Any) -> tuple[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return ('{"files":[{"path":"src/App.tsx","content":"app"},{"path":"src/index.css","content":""}]}', {})
    monkeypatch.setattr(runs, "generate", fake_generate)
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_initial_claim", "set", 1, "hash", "initial-claim", "hash", "CREATED", storage.now(), storage.now()))
    first = asyncio.create_task(runs.execute("run_initial_claim"))
    await started.wait()
    await asyncio.gather(*(runs.execute("run_initial_claim") for _ in range(3)))
    release.set()
    await first
    result = runs.read_run("run_initial_claim")
    assert calls == 1 and result is not None and result["model_requests"] == 1


def test_pixel_difference_requires_equal_dimensions_and_reports_raw_difference(tmp_path: Path) -> None:
    reference = io.BytesIO()
    Image.new("RGB", (4, 3), "white").save(reference, format="PNG")
    path = tmp_path / "candidate.png"
    Image.new("RGB", (4, 3), "white").save(path)
    same = _pixel_difference(reference.getvalue(), path)
    assert same["mean_channel_difference"] == 0 and same["image_data_url"].startswith("data:image/png;base64,")
    Image.new("RGB", (4, 3), "black").save(path)
    assert _pixel_difference(reference.getvalue(), path)["mean_channel_difference"] == 255
    Image.new("RGB", (4, 4), "white").save(path)
    with pytest.raises(HTTPException) as exc:
        _pixel_difference(reference.getvalue(), path)
    assert exc.value.status_code == 422 and "尺寸不同" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_visual_diff_uses_only_task_references(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    path = tmp_path / "runs" / "run_test" / "candidate" / "inspection-mobile.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (4, 3), "white").save(path)
    image = io.BytesIO()
    Image.new("RGB", (4, 3), "white").save(image, format="PNG")
    monkeypatch.setattr(d2c_routes, "read_run", lambda _id: {"source_set_id": "set", "source_set_revision": 1, "result": {"candidate_name": "candidate"}})
    monkeypatch.setattr(d2c_routes, "get_source_set", lambda *_args: {"sources": [{"input_id": "reference"}]})
    monkeypatch.setattr(d2c_routes, "get_input", lambda _id: {"input_type": "screenshot", "data": {"content_base64": base64.b64encode(image.getvalue()).decode()}})
    monkeypatch.setattr(d2c_routes, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    assert (await d2c_routes.visual_diff("run_test", "reference", "mobile"))["mean_channel_difference"] == 0
    with pytest.raises(HTTPException) as exc:
        await d2c_routes.visual_diff("run_test", "unrelated", "mobile")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_visual_diff_reference_viewport_capture(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    image = io.BytesIO()
    Image.new("RGB", (4, 3), "white").save(image, format="PNG")
    monkeypatch.setattr(d2c_routes, "read_run", lambda _id: {"status": "READY_FOR_REVIEW", "source_set_id": "set", "source_set_revision": 1, "result": {"candidate_name": "candidate"}})
    monkeypatch.setattr(d2c_routes, "get_source_set", lambda *_args: {"sources": [{"input_id": "reference"}]})
    monkeypatch.setattr(d2c_routes, "get_input", lambda _id: {"input_type": "screenshot", "data": {"content_base64": base64.b64encode(image.getvalue()).decode()}})
    async def capture(_run: str, _candidate: str, width: int, height: int) -> tuple[bytes, list[str]]:
        assert (width, height) == (4, 3)
        return image.getvalue(), ["页面存在脚本错误。"]
    monkeypatch.setattr(d2c_routes, "capture_reference_viewport", capture)
    result = await d2c_routes.visual_diff("run_test", "reference", "reference")
    assert result["capture"] == "reference_viewport" and result["mean_channel_difference"] == 0
    assert result["warnings"] == ["页面存在脚本错误。"]
    assert base64.b64decode(result["candidate_image_data_url"].split(",", 1)[1]) == image.getvalue()


@pytest.mark.asyncio
async def test_reference_capture_reports_page_errors_and_overflow(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text('<style>body{width:900px;height:900px}</style><img src="missing.png"><script>throw new Error("test")</script>', encoding="utf-8")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(inspection, "preview_url", lambda *_args: f"http://127.0.0.1:{server.server_port}/")
    try:
        screenshot, warnings = await inspection.capture_reference_viewport("run_test", "candidate", 390, 400)
        with Image.open(io.BytesIO(screenshot)) as image:
            assert image.size == (390, 400)
        assert "页面存在脚本错误。" in warnings
        assert "页面资源返回错误状态。" in warnings
        assert "页面存在水平溢出，视口外内容未纳入比较。" in warnings
        assert "页面存在视口下方内容，未纳入比较。" in warnings
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_main_app_only_exposes_tracked_model_generation() -> None:
    from main import app
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/generate-code" not in paths
    assert "/run_evals" not in paths and "/run_evals_stream" not in paths
    assert "/api/d2c/v1/runs" in paths
    assert "/openai-input-compare" in paths


@pytest.mark.parametrize("model_ready,token_limit", [(False, None), (True, 1000)])
def test_repair_checks_current_model_configuration(tmp_path: Path, monkeypatch: MonkeyPatch, model_ready: bool, token_limit: int | None) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_ready=model_ready, token_limit=token_limit,
        cost_limit_micro_usd=None, model_request_limit=2, repair_limit=1))
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   ("run_repair_config", "set", 1, "hash", "config-key", "hash", "READY_FOR_REVIEW", '{"files":[]}', storage.now(), storage.now()))
    with pytest.raises(HTTPException) as exc:
        runs.request_repair("run_repair_config", "change", "repair-config-key")
    assert getattr(exc.value, "status_code", None) == 422
    row = runs.read_run("run_repair_config")
    assert row is not None and row["model_requests"] == 0 and row["status"] == "READY_FOR_REVIEW"


@pytest.mark.asyncio
async def test_failed_build_report_distinguishes_unrun_checks(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_request_limit=2))
    monkeypatch.setattr(runs, "get_source_set", lambda *_args: {})
    monkeypatch.setattr(runs, "build_candidate", lambda *_args: {"status": "FAIL", "message": "build failed"})

    async def fake_generate(_settings: Any, _source_set: Any) -> tuple[str, dict[str, Any]]:
        return ('{"files":[{"path":"src/App.tsx","content":"invalid"},{"path":"src/index.css","content":""}]}', {})

    monkeypatch.setattr(runs, "generate", fake_generate)
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_failed_report", "set", 1, "hash", "failed-report", "hash", "CREATED", storage.now(), storage.now()))
    await runs.execute("run_failed_report")
    run = runs.read_run("run_failed_report")
    assert run is not None and run["status"] == "FAILED"
    checks = {check["id"]: check["status"] for check in run["result"]["checks"]}
    assert checks == {"build": "FAIL", "visual": "NOT_RUN", "interactions": "NOT_RUN", "manual_review": "NOT_RUN"}


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", ["none", "stop", "restart"])
async def test_repair_execution_claim_prevents_duplicate_model_calls(tmp_path: Path, monkeypatch: MonkeyPatch, interrupt: str) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_ready=True, token_limit=None,
        cost_limit_micro_usd=None, model_request_limit=2, repair_limit=1))
    monkeypatch.setattr(runs, "get_source_set", lambda *_args: {})
    monkeypatch.setattr(runs, "build_candidate", lambda *_args: {"status": "FAIL", "message": "build failed"})
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fake_generate(*_args: Any, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return ('{"files":[{"path":"src/App.tsx","content":"app"},{"path":"src/index.css","content":""}]}', {})

    monkeypatch.setattr(runs, "generate", fake_generate)
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,calls,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("run_claim", "set", 1, "hash", "claim-key", "hash", "READY_FOR_REVIEW", 1,
                    '{"files":[]}', storage.now(), storage.now()))
    assert runs.request_repair("run_claim", "change", "repair-key") is True
    assert runs.request_repair("run_claim", "change", "repair-key") is False
    first = asyncio.create_task(runs.execute_repair("run_claim", "change"))
    await started.wait()
    await asyncio.gather(*(runs.execute_repair("run_claim", "change") for _ in range(3)))
    if interrupt == "stop":
        assert runs.cancel_run("run_claim")["status"] == "UNKNOWN_EXTERNAL"
    elif interrupt == "restart":
        runs.recover_interrupted_runs()
    release.set()
    await first
    await runs.execute_repair("run_claim", "change")
    run = runs.read_run("run_claim")
    assert run is not None and run["model_requests"] == 2 and run["repairs"] == 1
    assert run["status"] == ("FAILED" if interrupt == "none" else "UNKNOWN_EXTERNAL")
    assert calls == 1


@pytest.mark.asyncio
async def test_invalid_generation_can_be_repaired_once(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_ready=True, token_limit=None,
        cost_limit_micro_usd=None, model_request_limit=2, repair_limit=1))
    monkeypatch.setattr(runs, "get_source_set", lambda *_args: {})
    monkeypatch.setattr(runs, "build_candidate", lambda *_args: {"status": "FAIL", "message": "simulated build"})
    calls: list[str] = []
    async def fake_generate(_settings: Any, _source_set: Any, repair_context: str = "") -> tuple[str, dict[str, Any]]:
        calls.append(repair_context)
        if not repair_context:
            return "invalid model response", {}
        return ('{"files":[{"path":"src/App.tsx","content":"app"},{"path":"src/index.css","content":""}]}', {})
    monkeypatch.setattr(runs, "generate", fake_generate)
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_invalid", "set", 1, "hash", "invalid-key", "hash", "CREATED", storage.now(), storage.now()))
    await runs.execute("run_invalid")
    failed = runs.read_run("run_invalid")
    assert failed is not None and failed["status"] == "FAILED" and failed["result"]["files"] == []
    assert failed["result"]["checks"][0]["status"] == "NOT_RUN"
    assert runs.request_repair("run_invalid", "fix the response", "invalid-repair-key")
    await runs.execute_repair("run_invalid", "fix the response")
    repaired = runs.read_run("run_invalid")
    assert repaired is not None and repaired["model_requests"] == 2 and repaired["repairs"] == 1
    assert repaired["result"]["candidate_name"] == "candidate-2"
    assert "invalid model response" in calls[1]
    with pytest.raises(HTTPException):
        runs.request_repair("run_invalid", "again", "second-repair-key")


def test_storage_closes_connection_and_rolls_back(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    with pytest.raises(ValueError):
        with storage.connect() as db:
            db.execute("INSERT INTO inputs VALUES (?, ?, ?, ?, ?)", ("x", "spec", "hash", "{}", storage.now()))
            raise ValueError("rollback")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")
    assert storage.get_input("x") is None



@pytest.mark.asyncio
async def test_malformed_figma_url_returns_validation_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(inputs, "get_settings", lambda: SimpleNamespace(figma_token="configured", figma_bridge_client=Path("missing")))
    for importer in (inputs.import_figma, inputs.import_figma_mcp):
        with pytest.raises(HTTPException) as error:
            await importer("https://[bad/design/file?node-id=1-2")
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_figma_mcp_import_converts_node_and_png(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    png_data = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(png_data, format="PNG")
    encoded = base64.b64encode(png_data.getvalue()).decode("ascii")

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            payload = {"node": {"content": [{"type": "text", "text": json.dumps({"id": "1:2", "name": "Screen"})}]},
                       "screenshot": {"content": [{"type": "text", "text": json.dumps([{"base64": encoded}])}]}}
            return json.dumps(payload).encode("utf-8"), b""

    async def fake_exec(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(inputs, "get_settings", lambda: SimpleNamespace(
        figma_mode="mcp", figma_bridge_client=tmp_path / "bridge-client.mjs",
    ))
    monkeypatch.setattr(inputs.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(inputs.asyncio, "create_subprocess_exec", fake_exec)
    (tmp_path / "bridge-client.mjs").write_text("", encoding="utf-8")
    result = await inputs.import_figma_mcp("https://www.figma.com/design/Abc123/test?node-id=1-2")
    assert result["input_type"] == "figma" and result["data"]["source"] == "figma-mcp-bridge"


@pytest.mark.asyncio
async def test_figma_mcp_import_reports_bridge_tool_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            payload = {"node": {"isError": True, "content": [{"type": "text", "text": "No plugin connected"}]},
                       "screenshot": {"isError": True, "content": [{"type": "text", "text": "No plugin connected"}]}}
            return json.dumps(payload).encode("utf-8"), b""

    async def fake_exec(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(inputs, "get_settings", lambda: SimpleNamespace(
        figma_mode="mcp", figma_bridge_client=tmp_path / "bridge-client.mjs",
    ))
    monkeypatch.setattr(inputs.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(inputs.asyncio, "create_subprocess_exec", fake_exec)
    (tmp_path / "bridge-client.mjs").write_text("", encoding="utf-8")
    with pytest.raises(HTTPException, match="No plugin connected"):
        await inputs.import_figma_mcp("https://www.figma.com/design/Abc123/test?node-id=1-2")


@pytest.mark.asyncio
async def test_figma_mcp_timeout_terminates_owned_client(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    script = tmp_path / "bridge-client.mjs"
    script.write_text("setInterval(() => {}, 1000);", encoding="utf-8")
    monkeypatch.setattr(inputs, "get_settings", lambda: SimpleNamespace(figma_mode="mcp", figma_bridge_client=script))
    monkeypatch.setattr(inputs, "FIGMA_MCP_TIMEOUT_SECONDS", 0.5)
    real_exec = inputs.asyncio.create_subprocess_exec
    started: list[Any] = []

    async def capture_exec(*args: Any, **kwargs: Any) -> Any:
        process = await real_exec(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(inputs.asyncio, "create_subprocess_exec", capture_exec)
    with pytest.raises(HTTPException) as error:
        await inputs.import_figma_mcp("https://www.figma.com/design/Abc123/test?node-id=1-2")
    assert error.value.status_code == 504
    assert len(started) == 1 and started[0].returncode is not None


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree integration test")
def test_cancel_stops_owned_build_process_tree(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_build_cancel", "set", 1, "hash", "build-key", "hash", "BUILDING", storage.now(), storage.now()))
    result: list[dict[str, Any]] = []
    code = ('import subprocess,sys,time,pathlib; '
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
            'pathlib.Path("child.pid").write_text(str(p.pid)); time.sleep(60)')
    thread = threading.Thread(target=lambda: result.append(runner._run_build_command(
        "run_build_cancel", [sys.executable, "-c", code], tmp_path, 60)))
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path / "child.pid").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "child.pid").exists()
        child_pid = int((tmp_path / "child.pid").read_text())
        assert runs.cancel_run("run_build_cancel")["status"] == "CANCELLED"
        thread.join(timeout=15)
        assert not thread.is_alive()
        output = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid}", "/NH"], capture_output=True, text=True, timeout=10, check=False)
        assert str(child_pid) not in output.stdout
        assert result and result[0]["status"] != "PASS"
        assert runner._run_build_command("run_build_cancel", [sys.executable, "-c", "raise SystemExit(0)"], tmp_path, 5)["status"] == "CANCELLED"
    finally:
        runner.cancel_build("run_build_cancel")
        thread.join(timeout=15)


def test_preview_reuses_port_and_routes_each_candidate(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    settings: Any = SimpleNamespace(runtime_dir=tmp_path, preview_host="127.0.0.1", preview_port_start=0, preview_port_end=0)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    runner.close_previews()
    try:
        for run_id, candidate, content in (("run_first", "candidate", "first"), ("run_second", "candidate-2", "second")):
            dist = tmp_path / "runs" / run_id / candidate / "dist"
            dist.mkdir(parents=True)
            (dist / "index.html").write_text(content, encoding="utf-8")
            (dist / "asset.js").write_text(content + "-asset", encoding="utf-8")
        first = runner.preview_url("run_first", settings, "candidate")
        second = runner.preview_url("run_second", settings, "candidate-2")
        assert httpx.URL(first).port == httpx.URL(second).port
        assert httpx.get(first).text.startswith("first")
        assert httpx.get(second).text.startswith("second")
        assert "__d2c_selection.js" in httpx.get(first).text
        assert httpx.get(first + "__d2c_selection.js").status_code == 200
        assert httpx.get(first + "asset.js").text == "first-asset"
        special = tmp_path / "runs" / "run_first" / "candidate" / "dist" / "a%20b#中文.png"
        special.write_bytes(b"image-fixture")
        assert httpx.get(first + "a%2520b%23%E4%B8%AD%E6%96%87.png").content == b"image-fixture"
        assert httpx.get(second + "asset.js").text == "second-asset"
        assert httpx.get(first + "%2e%2e/%2e%2e/secret.txt").status_code == 404
    finally:
        runner.close_previews()


@pytest.mark.asyncio
async def test_preview_selection_intercepts_click_without_changing_exported_html(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    settings: Any = SimpleNamespace(runtime_dir=tmp_path, preview_host="127.0.0.1", preview_port_start=0, preview_port_end=0)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    runner.close_previews()
    dist = tmp_path / "runs" / "run_select" / "candidate" / "dist"
    dist.mkdir(parents=True)
    original = '<body><button>Target</button><script src="./app.js"></script></body>'
    (dist / "index.html").write_text(original, encoding="utf-8")
    (dist / "app.js").write_text('window.clicked=0;document.querySelector("button").addEventListener("click",()=>window.clicked++);', encoding="utf-8")
    try:
        url = runner.preview_url("run_select", settings)
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch(headless=True)
            except PlaywrightError:
                pytest.skip("Playwright Chromium is not installed")
            try:
                page = await browser.new_page()
                await page.set_content(f'<iframe sandbox="allow-scripts" src="{url}"></iframe>')
                frame = page.frame_locator("iframe")
                await frame.get_by_role("button", name="Target").wait_for()
                await page.evaluate('''() => {
                    window.addEventListener("message", (event) => { window.selectedMessage = event.data; });
                    document.querySelector("iframe").contentWindow.postMessage({type:"d2c-select-mode",enabled:true,token:"test-token"}, "*");
                }''')
                await frame.get_by_role("button", name="Target").click()
                await page.wait_for_function("() => window.selectedMessage?.type === 'd2c-element-selected'")
                result: Any = await page.evaluate("() => window.selectedMessage")
                assert result["token"] == "test-token" and "Target" in result["html"]
                assert await frame.locator("button").evaluate("() => window.clicked") == 0
                assert (dist / "index.html").read_text(encoding="utf-8") == original
            finally:
                await browser.close()
    finally:
        runner.close_previews()


@pytest.mark.asyncio
async def test_interaction_smoke_check_exercises_local_controls(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    settings: Any = SimpleNamespace(runtime_dir=tmp_path, preview_host="127.0.0.1", preview_port_start=0, preview_port_end=0)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(inspection, "get_settings", lambda: settings)
    runner.close_previews()
    dist = tmp_path / "runs" / "run_interactions" / "candidate" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<button id='button'>Go</button>"
        "<input aria-label='Name'><select><option value='one'>One</option><option value='two'>Two</option></select>"
        "<script src='./app.js'></script>",
        encoding="utf-8",
    )
    (dist / "app.js").write_text("document.querySelector('#button').addEventListener('click',()=>document.body.dataset.clicked='yes')", encoding="utf-8")
    try:
        result = await inspection.inspect_interactions("run_interactions", "candidate")
        assert result["id"] == "interaction_smoke" and result["status"] == "PASS", result
        assert "3 个控件" in result["message"]
    finally:
        runner.close_previews()


@pytest.mark.asyncio
async def test_interaction_smoke_without_supported_controls_is_not_run(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    settings: Any = SimpleNamespace(runtime_dir=tmp_path, preview_host="127.0.0.1", preview_port_start=0, preview_port_end=0)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(inspection, "get_settings", lambda: settings)
    runner.close_previews()
    dist = tmp_path / "runs" / "run_empty" / "candidate" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<input type='checkbox'><input type='file'>", encoding="utf-8")
    try:
        result = await inspection.inspect_interactions("run_empty", "candidate")
        assert result["id"] == "interaction_smoke" and result["status"] == "NOT_RUN", result
    finally:
        runner.close_previews()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_responses", "openai_chat_completions"])
async def test_provider_sends_one_request_with_image_and_selected_model(protocol: str, monkeypatch: MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-6-luna"
        assert "data:image/png;base64,YQ==" in request.content.decode()
        if protocol == "openai_responses":
            return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda **_kwargs: client_type(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(provider, "_materials", lambda _source: ("spec", ["data:image/png;base64,YQ=="]))
    settings: Any = SimpleNamespace(protocol=protocol, model="openai/gpt-6-luna", base_url="https://example.test/v1", api_key="test", provider_timeout=10)
    text, _usage = await provider.generate(settings, {})
    assert text == "{}" and len(seen) == 1


@pytest.mark.asyncio
async def test_provider_timeout_does_not_retry(monkeypatch: MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda **_kwargs: client_type(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(provider, "_materials", lambda _source: ("spec", []))
    settings: Any = SimpleNamespace(protocol="openai_responses", model="model", base_url="https://example.test/v1", api_key="test", provider_timeout=10)
    with pytest.raises(provider.ProviderError) as exc:
        await provider.generate(settings, {})
    assert exc.value.unknown and len(seen) == 1


@pytest.mark.asyncio
async def test_cancel_during_provider_call_does_not_build_or_overwrite_status(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_request_limit=2))
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_generate(_settings: Any, _source_set: Any) -> tuple[str, dict[str, Any]]:
        started.set()
        await release.wait()
        return ('{"files":[{"path":"src/App.tsx","content":"x"},{"path":"src/index.css","content":"x"}]}', {})

    monkeypatch.setattr(runs, "generate", fake_generate)
    monkeypatch.setattr(runs, "get_source_set", lambda *_args: {})
    monkeypatch.setattr(runs, "build_candidate", lambda *_args: pytest.fail("cancelled run must not build"))
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_cancel", "set", 1, "hash", "key", "hash", "CREATED", storage.now(), storage.now()))
    task = asyncio.create_task(runs.execute("run_cancel"))
    await started.wait()
    assert runs.cancel_run("run_cancel")["status"] == "UNKNOWN_EXTERNAL"
    release.set()
    await task
    snapshot = runs.read_run("run_cancel")
    assert snapshot is not None and snapshot["status"] == "UNKNOWN_EXTERNAL"
    assert snapshot["result"] is None


def test_restart_marks_interrupted_requests_without_retry(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    with storage.connect() as db:
        for status in ("GENERATING", "BUILDING"):
            db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (status, "set", 1, "hash", status, "hash", status, storage.now(), storage.now()))
    runs.recover_interrupted_runs()
    generated = runs.read_run("GENERATING")
    building = runs.read_run("BUILDING")
    assert generated is not None and generated["status"] == "UNKNOWN_EXTERNAL"
    assert building is not None and building["status"] == "FAILED"


def test_combined_sources_are_persisted_without_returning_image_bytes(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    image_buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "#abc123").save(image_buffer, format="PNG")
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    image_response = client.post("/api/d2c/v1/design-inputs", json={
        "input_type": "screenshot", "content": encoded, "name": "example.png",
    })
    assert image_response.status_code == 200
    image: dict[str, Any] = image_response.json()
    assert image["data"]["width"] == 16
    assert "content_base64" not in image["data"]
    spec_response = client.post("/api/d2c/v1/design-inputs", json={
        "input_type": "spec", "content": "# 任务列表\n- 支持搜索",
    })
    assert spec_response.status_code == 200
    spec: dict[str, Any] = spec_response.json()
    result = client.post("/api/d2c/v1/source-sets", json={
        "sources": [{"input_id": image["input_id"], "role": "style_reference"},
                    {"input_id": spec["input_id"], "role": "behavior_and_content"}],
        "instructions": "配色按截图，行为按 Spec",
        "authority_by_dimension": {"style": image["input_id"], "behavior": spec["input_id"]},
    })
    assert result.status_code == 200
    source_set: dict[str, Any] = result.json()
    assert len(source_set["sources"]) == 2
    assert source_set["confirmed"] is False
    assert client.get(f"/api/d2c/v1/source-sets/{source_set['source_set_id']}").json() == source_set
    assert client.get(f"/api/d2c/v1/design-inputs/{image['input_id']}").json()["data"].get("content_base64") is None
    assert client.post("/api/d2c/v1/design-inputs", json={"input_type": "screenshot", "content": "invalid!"}).status_code == 422


def test_confirmed_run_is_idempotent_and_calls_model_once(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(
        model_ready=True, token_limit=None, cost_limit_micro_usd=None, model_request_limit=2, repair_limit=1,
    ))
    call_count = 0

    async def fake_generate(_settings: Any, _source_set: dict[str, Any], repair_context: str = "") -> tuple[str, dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        return ('{"files":[{"path":"src/App.tsx","content":"export default function App() { return null; }"},'
                '{"path":"src/index.css","content":"body {}"}]}', {"input_tokens": 10})

    monkeypatch.setattr(runs, "generate", fake_generate)
    monkeypatch.setattr(runs, "build_candidate", lambda _run_id, _files, _name="candidate": {"status": "PASS", "message": "构建成功"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    source = client.post("/api/d2c/v1/design-inputs", json={"input_type": "spec", "content": "# 页面"}).json()
    source_set = client.post("/api/d2c/v1/source-sets", json={
        "sources": [{"input_id": source["input_id"]}], "instructions": "生成页面",
    }).json()
    body = {key: source_set[key] for key in ("source_set_id", "source_set_revision", "source_set_hash")}
    headers = {"Idempotency-Key": "test-create-once"}
    assert client.post("/api/d2c/v1/runs", json=body, headers=headers).status_code == 409
    assert client.post(f"/api/d2c/v1/source-sets/{body['source_set_id']}/confirm", json=body).status_code == 200
    first = client.post("/api/d2c/v1/runs", json=body, headers=headers)
    second = client.post("/api/d2c/v1/runs", json=body, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    snapshot = client.get(f"/api/d2c/v1/runs/{first.json()['run_id']}").json()
    assert snapshot["status"] == "READY_FOR_REVIEW"
    assert snapshot["model_requests"] == 1
    assert call_count == 1
    assert snapshot["result"]["checks"][1]["status"] == "NOT_RUN"
    assert next(check for check in snapshot["result"]["checks"] if check["id"] == "manual_review")["status"] == "MANUAL_REVIEW"
    repair_headers = {"Idempotency-Key": "test-repair-once"}
    repair_body = {"instruction": "修改标题"}
    assert client.post(f"/api/d2c/v1/runs/{snapshot['run_id']}/repair", json=repair_body, headers=repair_headers).status_code == 202
    assert client.post(f"/api/d2c/v1/runs/{snapshot['run_id']}/repair", json=repair_body, headers=repair_headers).status_code == 202
    assert client.post(f"/api/d2c/v1/runs/{snapshot['run_id']}/repair", json=repair_body,
                       headers={"Idempotency-Key": "test-repair-twice"}).status_code == 409
    repaired = client.get(f"/api/d2c/v1/runs/{snapshot['run_id']}").json()
    assert repaired["model_requests"] == 2
    assert repaired["repairs"] == 1
    assert repaired["result"]["candidate_name"] == "candidate-2"
    assert next(check for check in repaired["result"]["checks"] if check["id"] == "manual_review")["status"] == "MANUAL_REVIEW"
    assert call_count == 2


@pytest.mark.asyncio
async def test_figma_import_includes_node_and_reference_image(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(inputs, "get_settings", lambda: SimpleNamespace(figma_token="example-token"))
    image_buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(image_buffer, format="PNG")
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.host == "images.example.test":
            assert "X-Figma-Token" not in request.headers
            return httpx.Response(200, content=image_buffer.getvalue())
        assert request.headers["X-Figma-Token"] == "example-token"
        if request.url.path.endswith("/nodes"):
            return httpx.Response(200, json={"version": "v1", "nodes": {"1:2": {"document": {"name": "Page", "type": "FRAME"}}}})
        return httpx.Response(200, json={"images": {"1:2": "https://images.example.test/page.png"}})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(inputs.httpx, "AsyncClient", lambda **_kwargs: client_type(transport=httpx.MockTransport(handle)))
    result = await inputs.import_figma("https://www.figma.com/design/Abc123/test?node-id=1-2")
    snapshot = storage.get_input(result["input_id"])
    assert snapshot is not None
    assert snapshot["data"]["node_data"]["name"] == "Page"
    assert base64.b64decode(snapshot["data"]["content_base64"]) == image_buffer.getvalue()
    assert len(seen) == 3
    assert "example-token" not in json.dumps(result)


def test_three_sources_are_passed_together_to_generation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    monkeypatch.setattr(inputs, "get_settings", lambda: SimpleNamespace(figma_token="example-token"))
    monkeypatch.setattr(runs, "get_settings", lambda: SimpleNamespace(model_ready=True, token_limit=None,
        cost_limit_micro_usd=None, model_request_limit=2, repair_limit=1))
    image_buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(image_buffer, format="PNG")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "images.example.test":
            return httpx.Response(200, content=image_buffer.getvalue())
        if request.url.path.endswith("/nodes"):
            return httpx.Response(200, json={"version": "v1", "nodes": {"1:2": {"document": {"name": "Page", "type": "FRAME"}}}})
        return httpx.Response(200, json={"images": {"1:2": "https://images.example.test/page.png"}})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(inputs.httpx, "AsyncClient", lambda **_kwargs: client_type(transport=httpx.MockTransport(handle)))
    seen: list[dict[str, Any]] = []

    async def fake_generate(_settings: Any, source_set: dict[str, Any], repair_context: str = "") -> tuple[str, dict[str, Any]]:
        seen.append(source_set)
        return ('{"files":[{"path":"src/App.tsx","content":"export default function App() { return null; }"},'
                '{"path":"src/index.css","content":"body {}"}]}', {})

    monkeypatch.setattr(runs, "generate", fake_generate)
    monkeypatch.setattr(runs, "build_candidate", lambda *_args: {"status": "PASS", "message": "ok"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    image = client.post("/api/d2c/v1/design-inputs", json={"input_type": "screenshot", "content": encoded}).json()
    spec = client.post("/api/d2c/v1/design-inputs", json={"input_type": "spec", "content": "支持搜索"}).json()
    figma = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma", "content": "https://www.figma.com/design/Abc123/test?node-id=1-2"}).json()
    source_set = client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": item["input_id"]} for item in (image, spec, figma)],
        "instructions": "颜色按截图，交互按 Spec，布局按 Figma"}).json()
    body = {key: source_set[key] for key in ("source_set_id", "source_set_revision", "source_set_hash")}
    assert client.post(f"/api/d2c/v1/source-sets/{body['source_set_id']}/confirm", json=body).status_code == 200
    response = client.post("/api/d2c/v1/runs", json=body, headers={"Idempotency-Key": "three-source-test"})
    assert response.status_code == 202
    assert len(seen) == 1
    assert {source["input_type"] for source in seen[0]["sources"]} == {"screenshot", "spec", "figma"}
    assert seen[0]["instructions"] == "颜色按截图，交互按 Spec，布局按 Figma"
