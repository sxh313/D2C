"""FigmaToCode-style archive import without contacting a model or Figma."""

import base64
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pytest import MonkeyPatch

import design2code.provider as provider
import design2code.runner as runner
import design2code.storage as storage
from design2code.routes import router


def bundle(entries: list[tuple[str, bytes]]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in entries:
            info = zipfile.ZipInfo(name)
            info.filename = name  # Preserve backslashes when constructing a malformed Windows ZIP.
            archive.writestr(info, content)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


def client_for(tmp_path: Path, monkeypatch: MonkeyPatch) -> TestClient:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("path,kind", [("src/App.tsx", "vite"), ("app/page.tsx", "nextjs"), ("site/index.html", "html")])
def test_bundle_as_reference_and_asset(tmp_path: Path, monkeypatch: MonkeyPatch, path: str, kind: str) -> None:
    client = client_for(tmp_path, monkeypatch)
    payload = bundle([(path, b"<div>Example</div>"), ("public/images/logo.png", png())])
    response = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma_bundle", "name": "example.zip", "content": payload})
    assert response.status_code == 200
    item = response.json()
    assert item["data"]["format"] == kind and item["data"]["asset_count"] == 1
    assert "files" not in item["data"] and "assets" not in item["data"]
    stored = client.get(f"/api/d2c/v1/design-inputs/{item['input_id']}").json()
    assert "files" not in stored["data"] and "assets" not in stored["data"]
    source: dict[str, Any] = {"sources": [{"input_id": item["input_id"], "role": "reference", "scope": {}}],
              "instructions": "use this design", "authority_by_dimension": {}, "resolutions": []}
    context, images = provider._materials(source)
    assert path in context and "./images/logo.png" in context and images == []


def test_bundle_asset_url_encodes_special_characters(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    payload = bundle([("src/App.tsx", b"export default 1"), ("public/images/a%20b#中文.png", png())])
    response = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma_bundle", "content": payload})
    assert response.status_code == 200
    source: dict[str, Any] = {"sources": [{"input_id": response.json()["input_id"], "role": "reference", "scope": {}}],
                              "instructions": "", "authority_by_dimension": {}, "resolutions": []}
    context, _ = provider._materials(source)
    assert "./images/a%2520b%23%E4%B8%AD%E6%96%87.png" in context


@pytest.mark.parametrize("entries", [
    [("../escape.html", b"x")], [("/absolute.html", b"x")],
    [("src/App.tsx", b"x"), ("SRC/app.tsx", b"y")],
    [("src/App.tsx", b"x"), ("images/a.png", b"invalid")], [("readme.txt", b"x")],
])
def test_invalid_bundle_rejected(tmp_path: Path, monkeypatch: MonkeyPatch, entries: list[tuple[str, bytes]]) -> None:
    client = client_for(tmp_path, monkeypatch)
    response = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma_bundle", "content": bundle(entries)})
    assert response.status_code == 422


def test_bundle_asset_copied_into_candidate(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    response = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma_bundle", "content": bundle([("src/App.tsx", b"export default 1"), ("public/images/logo.png", png())])})
    input_id = response.json()["input_id"]
    source = client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": input_id}]}).json()
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_bundle", source["source_set_id"], 1, "hash", "bundle", "hash", "CREATED", storage.now(), storage.now()))
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path, build_timeout=10))
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "pnpm")
    def fake_build(_run: str, _args: list[str], directory: Path, _timeout: int) -> dict[str, Any]:
        (directory / "dist").mkdir(exist_ok=True)
        (directory / "dist" / "index.html").write_text("ok")
        return {"status": "PASS"}
    monkeypatch.setattr(runner, "_run_build_command", fake_build)
    assert runner.build_candidate("run_bundle", [{"path": "src/App.tsx", "content": "export default 1"}])["status"] == "PASS"
    assert (tmp_path / "runs/run_bundle/candidate/public/images/logo.png").read_bytes() == png()
