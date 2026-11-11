"""Contract tests use synthetic transport data, never claim real Figma acceptance."""
import base64
import copy
import json
import os
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from pytest import MonkeyPatch

import design2code.figma_conversion as conversion
import design2code.provider as provider
from design2code.inputs import import_figma_bundle
from design2code.storage import get_input
from design2code.settings import PROJECT_ROOT
from tests.test_design2code_bundle import bundle, png, client_for

PAYLOAD = bundle([("src/App.tsx", b"export default function App(){return <h1>Skeleton evidence</h1>}"),
                  ("public/images/logo.png", png())])


def test_artifact_is_content_addressed_and_retains_source(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    first = import_figma_bundle(PAYLOAD, "first.zip")
    second = import_figma_bundle(PAYLOAD, "renamed.zip")
    artifact = first["data"]["artifact"]
    assert artifact == second["data"]["artifact"]
    assert artifact["provenance"] == "user_declared"
    assert artifact["converter_version"] is None
    assert artifact["files"][0]["content_hash"].startswith("sha256:")
    assert artifact["assets"][0]["path"] == "public/images/logo.png"
    assert artifact["assets"][0]["source_path"] == "public/images/logo.png"
    stored = get_input(first["input_id"])
    assert stored and "Skeleton evidence" in stored["data"]["files"][0]["content"]
    assert base64.b64decode(stored["data"]["assets"][0]["content_base64"]) == png()
    assert "archive_base64" not in first["data"]
    assert "archive_base64" not in client.get(f"/api/d2c/v1/design-inputs/{first['input_id']}").json()["data"]
    assert client.get(f"/api/d2c/v1/design-inputs/{first['input_id']}/artifact-archive").content == base64.b64decode(PAYLOAD)
    src = client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": first["input_id"]}]}).json()
    assert src["sources"][0]["artifact"]["artifact_hash"] == artifact["artifact_hash"]
    changed = import_figma_bundle(bundle([("src/App.tsx", b"changed")]), "first.zip")
    assert changed["data"]["artifact"]["artifact_hash"] != artifact["artifact_hash"]


def wire(monkeypatch: MonkeyPatch, response: dict[str, Any] | None = None, mutate: str = "") -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    async def post(_self: Any, url: str, *, json: dict[str, Any]) -> httpx.Response:
        captured.append(json)
        result: dict[str, Any] = copy.deepcopy(response) if response is not None else {"data": {
            "kind": "figma-to-code", "converter": "FigmaToCode", "converterVersion": "test-converter",
            "fileKey": json["fileKey"], "nodeIds": ["12:34"], "nodeNames": ["Test"],
            "request_id": json["params"]["request_id"], "format": "vite", "warnings": ["font warning"],
            "zipBase64": PAYLOAD,
        }}
        if mutate:
            result["data"][mutate] = "mismatch"
        return httpx.Response(200, request=httpx.Request("POST", url), json=result)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return captured


@pytest.mark.asyncio
async def test_conversion_uses_same_importer_and_binds_request(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client_for(tmp_path, monkeypatch)
    calls = wire(monkeypatch)
    result = await conversion.import_figma_conversion("https://www.figma.com/design/TestFile/Page?node-id=12-34")
    artifact = result["data"]["artifact"]
    assert result["input_type"] == "figma_bundle"
    assert artifact["transport"] == "desktop_bridge"
    assert artifact["source"]["node_ids"] == ["12:34"]
    assert artifact["request_id"] == calls[0]["params"]["request_id"]
    assert artifact["warnings"][0] == "font warning"
    assert artifact["provenance"] == "plugin_execution"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["request_id", "nodeIds", "fileKey", "kind", "format"])
async def test_conversion_rejects_mismatched_response(monkeypatch: MonkeyPatch, field: str) -> None:
    wire(monkeypatch, mutate=field)
    with pytest.raises(HTTPException) as failure:
        await conversion.import_figma_conversion("https://www.figma.com/design/TestFile/Page?node-id=12-34")
    assert cast(Any, failure.value.detail)["code"] == "INVALID_RESULT"


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code", [
    ("No plugin connected for fileKey", "NO_SESSION"),
    ("EMPTY_SELECTION", "EMPTY_SELECTION"), ("SELECTION_MISMATCH", "SELECTION_MISMATCH"),
    ("ASSET_FAILED: bad image", "ASSET_FAILED"), ("Unknown request type: d2c_convert_selection", "PLUGIN_UPDATE_REQUIRED"),
    ("Request timed out (3 minutes)", "TIMEOUT"), ("conversion error", "CONVERSION_FAILED"),
])
async def test_conversion_errors_do_not_become_inputs(monkeypatch: MonkeyPatch, error: str, code: str) -> None:
    calls = wire(monkeypatch, {"error": error})
    with pytest.raises(HTTPException) as failure:
        await conversion.import_figma_conversion("https://www.figma.com/design/TestFile/Page?node-id=12-34")
    assert cast(Any, failure.value.detail)["code"] == code
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_agent_receives_actual_artifact_code_and_spec(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    artifact = import_figma_bundle(PAYLOAD, "source.zip")
    spec: dict[str, Any] = client.post("/api/d2c/v1/design-inputs", json={"input_type": "spec", "content": "点击打开弹窗"}).json()
    image: dict[str, Any] = client.post("/api/d2c/v1/design-inputs", json={
        "input_type": "screenshot", "content": base64.b64encode(png()).decode(),
    }).json()
    source = client.post("/api/d2c/v1/source-sets", json={
        "sources": [{"input_id": item["input_id"]} for item in [artifact, spec, image]],
        "instructions": "保留结构并修改颜色",
    }).json()
    import agent.runner
    import prompts.pipeline
    captured: dict[str, Any] = {}
    async def prompt_messages(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []
    async def agent_run(_self: Any, *_args: Any) -> str:
        return "<html><body>test</body></html>"
    monkeypatch.setattr(prompts.pipeline, "build_prompt_messages", prompt_messages)
    monkeypatch.setattr(agent.runner.Agent, "run", agent_run)
    settings: Any = SimpleNamespace(api_key="test", base_url="https://example.invalid", model="openai/gpt-6-luna", model_request_limit=2)
    text, _ = await provider.generate_agent(settings, source)
    assert json.loads(text)["engine"] == "screenshot-to-code-agent"
    prompt = captured["prompt"]
    assert "Skeleton evidence" in prompt["text"]
    assert "点击打开弹窗" in prompt["text"]
    assert "保留结构并修改颜色" in prompt["text"]
    assert artifact["data"]["artifact"]["artifact_hash"] in prompt["text"]
    assert "./images/logo.png" in prompt["text"]
    assert len(prompt["images"]) == 1


@pytest.mark.skipif(os.environ.get("D2C_REAL_BUILD_TEST") != "1", reason="requires a real local Vite build")
def test_recorded_plugin_zip_builds_without_model(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Re-import a previously captured genuine ZIP; NOT a new live Figma conversion."""
    import design2code.runner as runner
    import design2code.runs as runs
    from design2code.storage import connect, now
    client = client_for(tmp_path, monkeypatch)
    raw = (PROJECT_ROOT / "examples/fixed-inputs/figma-plugin-image/reference.zip").read_bytes()
    imported = import_figma_bundle(base64.b64encode(raw).decode(), "reference.zip")
    original = get_input(imported["input_id"])
    assert original
    files = original["data"]["files"]
    app = next(file["content"] for file in files if file["path"] == "src/App.tsx")
    candidate = runs.parse_files(json.dumps({"files": [
        {"path": "src/App.tsx", "content": app},
        {"path": "src/index.css", "content": "body { margin: 0; }"},
    ]}))
    source = client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": imported["input_id"]}]}).json()
    with connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_artifact_real", source["source_set_id"], 1, source["source_set_hash"],
                    "artifact-real", "hash", "BUILDING", now(), now()))
    settings: Any = SimpleNamespace(runtime_dir=tmp_path, build_timeout=180, preview_host="127.0.0.1",
                               preview_port_start=19410, preview_port_end=19420)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    assert runner.build_candidate("run_artifact_real", candidate)["status"] == "PASS"
    try:
        url = runner.preview_url("run_artifact_real", settings)
        with urllib.request.urlopen(url) as response:
            assert response.status == 200
        for asset in original["data"]["assets"]:
            with urllib.request.urlopen(url + asset["path"]) as response:
                assert response.read() == base64.b64decode(asset["content_base64"])
    finally:
        runner.close_previews()
