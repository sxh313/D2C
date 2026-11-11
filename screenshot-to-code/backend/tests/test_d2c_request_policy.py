"""Offline SDK-boundary tests, not evidence of real provider compatibility."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from openai import AsyncOpenAI, InternalServerError

import agent.providers.factory as factory
import design2code.runs as runs
import design2code.storage as storage
from agent.engine import AgentEngine
from agent.providers.openai import OpenAIProviderSession
from agent.request_policy import RequestLimitError, RequestPolicy
from agent.state import AgentFileState
from agent.tools import AgentToolRuntime, ToolCall
from design2code.provider import ProviderError
from llm import Llm


async def sink(*_args: Any, **_kwargs: Any) -> None:
    pass


def sdk_transport(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if fail:
            return httpx.Response(503, json={"error": {"message": "synthetic-secret-do-not-log"}})
        item: dict[str, Any] = {"id": "fc_test", "call_id": "call_test", "type": "function_call",
                "name": "create_file", "arguments": json.dumps({"path": "index.html",
                "content": "<html><body><h1>Tool output</h1></body></html>"})}
        event: dict[str, Any] = {"type": "response.output_item.done", "output_index": 0, "item": item}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                             content=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")

    def client(**kwargs: Any) -> AsyncOpenAI:
        assert kwargs["max_retries"] == 0
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))

    monkeypatch.setattr(factory, "AsyncOpenAI", client)
    return sent


def setup_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str = "CREATED", calls: int = 0) -> None:
    settings: Any = SimpleNamespace(runtime_dir=tmp_path, model_request_limit=2, repair_limit=1,
        model_ready=True, token_limit=None, cost_limit_micro_usd=None, api_key="unit-test-key",
        base_url="https://example.invalid/v1", model="openai/gpt-6-luna", provider_timeout=1)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(runs, "get_settings", lambda: settings)
    monkeypatch.setattr(runs, "get_source_set", lambda *_: {
        "sources": [], "instructions": "Build test", "authority_by_dimension": {}, "resolutions": []})
    monkeypatch.setattr(runs, "build_candidate", lambda *_: {"status": "FAIL", "message": "synthetic build"})
    monkeypatch.setenv("LOGS_PATH", str(tmp_path / "logs"))
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,calls,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("run_policy", "set", 1, "hash", "key", "hash", status, calls, '{"files":[]}', storage.now(), storage.now()))


@pytest.mark.asyncio
async def test_actual_sdk_boundary_counts_initial_and_repair_without_third_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_run(tmp_path, monkeypatch)
    sent = sdk_transport(monkeypatch)
    await runs.execute("run_policy")
    first = runs.read_run("run_policy")
    assert first and first["model_requests"] == 1
    assert first["result"]["tool_policy"]["agent_completion"] == "request_limit_reached"
    assert "Tool output" in first["result"]["files"][0]["content"]
    assert any(event["name"] == "create_file" and event.get("ok") is True
               for event in first["result"]["tools"])
    assert any(check["id"] == "agent_feedback" and check["status"] == "NOT_RUN"
               for check in first["result"]["checks"])
    assert runs.request_repair("run_policy", "change", "repair-key")
    # Merely queuing a repair does not pretend the request has been sent.
    queued = runs.read_run("run_policy")
    assert queued and queued["model_requests"] == 1
    await asyncio.gather(runs.execute_repair("run_policy", "change"), runs.execute_repair("run_policy", "change"))
    final = runs.read_run("run_policy")
    assert final and final["model_requests"] == 2 and final["repairs"] == 1
    assert len(sent) == 2
    assert all("max_output_tokens" not in body for body in sent)
    assert all(body["model"] == "openai/gpt-6-luna" for body in sent)
    assert all({tool["name"] for tool in body["tools"]} <= RequestPolicy(1).allowed_tools for body in sent)
    with pytest.raises(HTTPException):
        runs.request_repair("run_policy", "again", "another-key")
    with storage.connect() as db:
        events = db.execute("SELECT payload_json FROM run_events WHERE run_id=? AND type='MODEL_REQUEST' ORDER BY seq", ("run_policy",)).fetchall()
    assert [json.loads(row[0])["model_request"] for row in events] == [1, 2]


@pytest.mark.asyncio
async def test_failed_sdk_request_is_counted_once_and_public_error_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_run(tmp_path, monkeypatch)
    sent = sdk_transport(monkeypatch, fail=True)
    await runs.execute("run_policy")
    row = runs.read_run("run_policy")
    assert row and row["model_requests"] == 1 and row["status"] == "UNKNOWN_EXTERNAL"
    assert len(sent) == 1  # HTTP 503 would normally trigger two SDK retries.
    assert "synthetic-secret" not in json.dumps(row)
    for path in (tmp_path / "logs").rglob("*.json*"):
        assert "synthetic-secret" not in path.read_text(encoding="utf-8")


def test_request_claim_is_atomic_and_does_not_clamp_real_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_run(tmp_path, monkeypatch, status="GENERATING")
    def claim(_index: int) -> bool:
        try:
            runs.request_claimer("run_policy", "GENERATING")("openai", "test")
            return True
        except ProviderError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(claim, range(8)))
    row = runs.read_run("run_policy")
    assert sum(claimed) == 2 and row and row["model_requests"] == 2


def test_stopped_run_cannot_claim_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_run(tmp_path, monkeypatch, status="CANCELLED")
    with pytest.raises(ProviderError):
        runs.request_claimer("run_policy", "GENERATING")("openai", "test")
    row = runs.read_run("run_policy")
    assert row and row["model_requests"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["extract_assets", "generate_images", "edit_images", "remove_backgrounds", "save_assets", "screenshot_preview"])
async def test_hidden_tool_calls_are_blocked_at_runtime(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Disabled tool reached an external implementation")
    monkeypatch.setattr("agent.tools.runtime.run_extract_assets", forbidden)
    monkeypatch.setattr("agent.tools.runtime.run_save_assets", forbidden)
    monkeypatch.setattr("agent.tools.runtime.run_screenshot_preview", forbidden)
    runtime = AgentToolRuntime(AgentFileState(), False, None, None, allowed_tools=RequestPolicy(1).allowed_tools)
    monkeypatch.setattr(runtime, "_generate_images", forbidden)
    monkeypatch.setattr(runtime, "_edit_images", forbidden)
    monkeypatch.setattr(runtime, "_remove_backgrounds", forbidden)
    result = await runtime.execute(ToolCall("id", name, {}))
    assert not result.ok and result.summary["error"] == "TOOL_DISABLED_BY_POLICY"


@pytest.mark.asyncio
async def test_policy_claim_occurs_before_transport_and_survives_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = sdk_transport(monkeypatch, fail=True)
    policy = RequestPolicy(1)
    session = factory.create_provider_session(Llm.GPT_6_LUNA_LOW, [], False, "test", "https://example.invalid", None, None, None,
                                               screenshot_enabled=False, request_policy=policy)
    try:
        with pytest.raises(InternalServerError):
            await session.stream_turn(sink)
        with pytest.raises(RequestLimitError):
            await session.stream_turn(sink)
        assert len(sent) == policy.requests == 1
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_native_session_retains_output_token_default() -> None:
    calls: list[dict[str, Any]] = []
    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="data: [DONE]\n\n")
    client = AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    session = OpenAIProviderSession(client, Llm.GPT_6_LUNA_LOW, [], [])
    try:
        await session.stream_turn(sink)
        assert calls[0]["max_output_tokens"] == 50000
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_bounded_engine_does_not_apply_native_cost_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk_transport(monkeypatch)
    monkeypatch.setattr(OpenAIProviderSession, "total_cost_usd", lambda _: 1_000_000.0)
    engine = AgentEngine(sink, 0, "test", "https://example.invalid", None, None, None, False,
                         max_turns=1, enable_screenshot_preview=False, request_policy=RequestPolicy(1))
    assert "Tool output" in await engine.run(Llm.GPT_6_LUNA_LOW, [])
    assert engine.completion_status == "request_limit_reached"
