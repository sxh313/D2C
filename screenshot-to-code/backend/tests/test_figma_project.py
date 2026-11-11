"""Project preservation and SDK tool wiring. Synthetic inputs are not live Figma evidence."""
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import design2code.provider as provider
import design2code.runs as runs
from agent.state import AgentFileState
from agent.tools import AgentToolRuntime, ToolCall
from design2code.figma_project import figma_seed
from design2code.inputs import import_figma_bundle
from tests.test_d2c_request_policy import sdk_transport, setup_run
from tests.test_design2code_bundle import bundle, png, client_for

APP = 'import "./theme.css";\nexport default function App(){return <main><h1>Original title</h1><img src="/images/logo.png" /></main>}'
STYLE = 'main { color: #123456; }'
PAYLOAD = bundle([("src/App.tsx", APP.encode()), ("src/theme.css", STYLE.encode()),
                  ("src/main.tsx", b"untrusted entrypoint is preserved in original ZIP"),
                  ("src/util.ts", b"export const original = 42;"),
                  ("public/images/logo.png", png())])


def source_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    client = client_for(tmp_path, monkeypatch)
    imported = import_figma_bundle(PAYLOAD, "synthetic.zip")
    return client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": imported["input_id"]}]}).json()


@pytest.mark.asyncio
async def test_conversion_only_uses_real_imported_source_without_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_for(tmp_path, monkeypatch)
    seed = figma_seed(source)
    assert seed and seed["files"]["src/theme.css"] == STYLE
    assert "src/main.tsx" not in seed["files"]
    sent = sdk_transport(monkeypatch)
    text, usage = await provider.generate_agent(runs.get_settings(), source)
    files = {file["path"]: file["content"] for file in json.loads(text)["files"]}
    assert files["src/theme.css"] == STYLE and "./images/logo.png" in files["src/App.tsx"]
    assert "dangerouslySetInnerHTML" not in files["src/App.tsx"]
    assert files["src/util.ts"] == "export const original = 42;"
    assert usage["model_requests"] == 0 and usage["engine"] == "figma-to-code" and sent == []
    assert usage["project"]["artifact_hash"] == seed["artifact_hash"]
    lineage = {file["path"]: file for file in usage["project"]["files"]}
    assert lineage["src/App.tsx"]["change"] == "unchanged"
    assert lineage["src/index.css"]["change"] == "added"
    assert lineage["src/index.css"]["baseline_kind"] == "template_default"


@pytest.mark.asyncio
async def test_project_sdk_edits_correct_file_and_preserves_untouched_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_for(tmp_path, monkeypatch)
    setup_run(tmp_path, monkeypatch)
    source["instructions"] = "Change title and add a component"
    sent = sdk_transport(monkeypatch, tools=[
        {"id": "fc1", "call_id": "edit1", "type": "function_call", "name": "edit_file",
         "arguments": json.dumps({"path": "src/App.tsx", "old_text": "Original title", "new_text": "Updated title"})},
        {"id": "fc2", "call_id": "create2", "type": "function_call", "name": "create_file",
         "arguments": json.dumps({"path": "src/components/Badge.tsx", "content": "export const Badge = () => <span>New</span>;"})},
    ])
    text, usage = await provider.generate_agent(runs.get_settings(), source)
    files = {file["path"]: file["content"] for file in runs.parse_files(text)}
    assert len(sent) == 1 and "Updated title" in files["src/App.tsx"]
    assert files["src/theme.css"] == STYLE and files["src/util.ts"] == "export const original = 42;"
    assert "src/components/Badge.tsx" in files
    assert "dangerouslySetInnerHTML" not in files["src/App.tsx"]
    lineage = {file["path"]: file for file in usage["project"]["files"]}
    assert lineage["src/App.tsx"]["change"] == "modified"
    assert lineage["src/theme.css"]["change"] == "unchanged"
    assert lineage["src/components/Badge.tsx"]["change"] == "added"
    assert usage["tool_policy"]["agent_completion"] == "request_limit_reached"
    assert {event["name"] for event in usage["tools"] if event.get("ok")} == {"edit_file", "create_file"}


@pytest.mark.asyncio
async def test_project_repair_edits_previous_candidate_not_original_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_for(tmp_path, monkeypatch)
    setup_run(tmp_path, monkeypatch)
    sent = sdk_transport(monkeypatch, tools=[
        {"id": "fc", "call_id": "edit", "type": "function_call", "name": "edit_file",
         "arguments": json.dumps({"path": "src/App.tsx", "old_text": "Prior candidate", "new_text": "Repaired"})},
    ])
    repair = json.dumps({"files": [{"path": "src/App.tsx", "content": APP.replace("Original title", "Prior candidate")},
                                   {"path": "src/extra.ts", "content": "export const saved = true;"}],
                         "instruction": "repair title"})
    text, usage = await provider.generate_agent(runs.get_settings(), source, repair_context=repair)
    files = {file["path"]: file["content"] for file in runs.parse_files(text)}
    assert "Repaired" in files["src/App.tsx"] and "src/extra.ts" in files
    assert usage["project"]["operations"] == ["src/App.tsx"] and len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../../.env", "src/../App.tsx", "src/main.tsx", "package.json", "src/.env.ts", "src\\App.tsx"])
async def test_project_tool_rejects_reserved_and_unsafe_paths(path: str) -> None:
    original = {"src/App.tsx": APP}
    runtime = AgentToolRuntime(AgentFileState(), False, None, None, project_files=original)
    result = await runtime.execute(ToolCall("id", "create_file", {"path": path, "content": "bad"}))
    assert not result.ok and runtime.project_files == original and runtime.project_writes == []


def test_conversion_only_run_does_not_require_model_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_for(tmp_path, monkeypatch)
    client = client_for(tmp_path, monkeypatch)
    setup_run(tmp_path, monkeypatch)
    # Delete only the synthetic test Run created by the fixture.
    from design2code.storage import connect
    with connect() as db:
        db.execute("DELETE FROM runs WHERE id='run_policy'")
    monkeypatch.setattr(runs, "get_source_set", lambda *_: source)
    settings: Any = runs.get_settings()
    settings.model_ready = False
    client.post(f"/api/d2c/v1/source-sets/{source['source_set_id']}/confirm", json={
        "source_set_revision": 1, "source_set_hash": source["source_set_hash"]})
    created, fresh = runs.create_run(source["source_set_id"], 1, source["source_set_hash"], "offline-convert")
    assert fresh and created["status"] == "CREATED"
    source["instructions"] = "Needs a model"
    with pytest.raises(HTTPException) as error:
        runs.create_run(source["source_set_id"], 1, source["source_set_hash"], "requires-model")
    assert error.value.status_code == 422


def test_tailwind_four_project_is_explicitly_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    imported = import_figma_bundle(bundle([("src/App.tsx", APP.encode()), ("src/index.css", b'@import "tailwindcss";')]), "tailwind4.zip")
    source = client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": imported["input_id"]}]}).json()
    with pytest.raises(ValueError, match="Tailwind 4"):
        figma_seed(source)
