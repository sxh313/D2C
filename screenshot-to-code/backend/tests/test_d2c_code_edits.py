"""Offline revision gates; these tests are not live browser acceptance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import design2code.code_edits as edits
import design2code.runs as runs
from design2code.storage import connect, json_encode
from tests.test_d2c_request_policy import setup_run


FILES = [{"path": "src/App.tsx", "content": "export default function App(){return <h1>Original</h1>}"},
         {"path": "src/index.css", "content": "body { margin: 0; }"}]
CHANGED = [{"path": "src/App.tsx", "content": FILES[0]["content"].replace("Original", "Edited")}, FILES[1]]


def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    setup_run(tmp_path, monkeypatch, status="READY_FOR_REVIEW", calls=1)
    monkeypatch.setattr(edits, "get_settings", runs.get_settings)
    monkeypatch.setattr(edits, "get_source_set", runs.get_source_set)
    monkeypatch.setattr(edits, "figma_seed", lambda *_: None)
    result: dict[str, Any] = {"files": FILES, "engine": "screenshot-to-code-agent", "model": "configured-model",
              "candidate_name": "candidate", "checks": [{"id": "build", "status": "PASS"}]}
    with connect() as db:
        db.execute("UPDATE runs SET result_json=? WHERE id='run_policy'", (json_encode(result),))
    return edits.candidate_hash("hash", result)


@pytest.mark.asyncio
async def test_manual_build_is_durable_idempotent_and_does_not_call_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = ready(tmp_path, monkeypatch)
    monkeypatch.setattr(runs, "generate", lambda *_a, **_k: pytest.fail("manual edit called provider"))
    built: list[Any] = []
    def build(*args: Any) -> dict[str, str]:
        built.append(args)
        return {"status": "PASS", "message": "test build"}
    async def inspection(*_args: Any) -> dict[str, str]:
        return {"id": "viewport", "status": "PASS", "message": "test only"}
    monkeypatch.setattr(edits, "build_candidate", build)
    monkeypatch.setattr(edits, "inspect_candidate", inspection)
    monkeypatch.setattr(edits, "inspect_interactions", inspection)
    assert edits.request_code_edit("run_policy", base, CHANGED, "manual-key-1")
    assert not edits.request_code_edit("run_policy", base, CHANGED, "manual-key-1")
    pending = runs.read_run("run_policy")
    assert pending and pending["repairs"] == 1 and pending["model_requests"] == 1
    assert pending["result"]["previous_candidate"]["files"] == FILES
    await edits.execute_code_edit("run_policy")
    await edits.execute_code_edit("run_policy")
    assert len(built) == 1 and built[0][1] == CHANGED
    final = runs.read_run("run_policy")
    assert final and final["status"] == "READY_FOR_REVIEW"
    assert final["result"]["revision"]["changed_files"] == ["src/App.tsx"]
    assert final["result"]["engine"] == "manual-code-edit" and final["model_requests"] == 1
    assert not edits.request_code_edit("run_policy", base, CHANGED, "manual-key-1")
    with pytest.raises(HTTPException) as exhausted:
        runs.request_repair("run_policy", "more edits", "another-key")
    assert exhausted.value.status_code == 409


@pytest.mark.parametrize("case", ["stale", "unchanged", "missing", "unsafe", "duplicate", "repaired"])
def test_rejects_invalid_edit_without_mutating_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    base = ready(tmp_path, monkeypatch)
    files = CHANGED
    if case == "stale": base = "0" * 64
    if case == "unchanged": files = FILES
    if case == "missing": files = CHANGED + [{"path": "src/new.ts", "content": "export const x=1;"}]
    if case == "unsafe": files = CHANGED + [{"path": "../.env", "content": "bad"}]
    if case == "duplicate": files = CHANGED + [CHANGED[0]]
    if case == "repaired":
        with connect() as db: db.execute("UPDATE runs SET repairs=1 WHERE id='run_policy'")
    before = runs.read_run("run_policy")
    with pytest.raises(HTTPException):
        edits.request_code_edit("run_policy", base, files, "invalid-edit")
    assert runs.read_run("run_policy") == before


def test_concurrent_manual_and_model_repair_share_one_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = ready(tmp_path, monkeypatch)
    def claim(index: int) -> str:
        try:
            if index % 2:
                edits.request_code_edit("run_policy", base, CHANGED, f"manual-{index}")
            else:
                runs.request_repair("run_policy", "fix", f"model-{index}")
            return "accepted"
        except HTTPException:
            return "rejected"
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(claim, range(8)))
    assert outcomes.count("accepted") == 1
    run = runs.read_run("run_policy")
    assert run and run["repairs"] == 1 and run["model_requests"] == 1


@pytest.mark.asyncio
async def test_failed_manual_build_keeps_original_and_never_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = ready(tmp_path, monkeypatch)
    monkeypatch.setattr(edits, "build_candidate", lambda *_: {"status": "FAIL", "message": "syntax error"})
    assert edits.request_code_edit("run_policy", base, CHANGED, "failed-code")
    await edits.execute_code_edit("run_policy")
    run = runs.read_run("run_policy")
    assert run and run["status"] == "FAILED" and run["model_requests"] == 1
    assert run["result"]["files"] == CHANGED and run["result"]["previous_candidate"]["files"] == FILES
    assert run["result"]["checks"][0]["status"] == "FAIL"
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM repair_execution_claims").fetchone()[0] == 1


def test_reused_key_cannot_change_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = ready(tmp_path, monkeypatch)
    assert edits.request_code_edit("run_policy", base, CHANGED, "same-key")
    with pytest.raises(HTTPException) as conflict:
        edits.request_code_edit("run_policy", base, FILES, "same-key")
    assert conflict.value.status_code == 409
