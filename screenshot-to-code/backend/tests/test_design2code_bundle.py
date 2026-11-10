"""FigmaToCode-style archive import without contacting a model or Figma."""

import base64
import io
import json
import os
import re
import urllib.parse
import urllib.request
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
import design2code.runs as runs
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


def test_corrupt_png_returns_validation_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    data = bytearray(png())
    data[-5] ^= 1  # Break the IEND checksum while keeping a recognizable PNG.
    response = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma_bundle", "content": bundle([("src/App.tsx", b"x"), ("images/broken.png", bytes(data))])})
    assert response.status_code == 422
    screenshot = client.post("/api/d2c/v1/design-inputs", json={"input_type": "screenshot", "name": "broken.png", "content": "data:image/png;base64," + base64.b64encode(data).decode()})
    assert screenshot.status_code == 422


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


def test_visual_references_include_role_and_assigned_dimensions(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    screenshot = client.post("/api/d2c/v1/design-inputs", json={
        "input_type": "screenshot", "name": "reference.png",
        "content": "data:image/png;base64," + base64.b64encode(png()).decode(),
    }).json()
    input_id = screenshot["input_id"]
    source = client.post("/api/d2c/v1/source-sets", json={
        "sources": [{"input_id": input_id, "role": "颜色参考"}],
        "authority_by_dimension": {"style": input_id, "content": "instructions"},
    }).json()
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_visual_role", source["source_set_id"], 1, "hash", "visual-role", "hash", "CREATED", storage.now(), storage.now()))
    response = client.get("/api/d2c/v1/runs/run_visual_role/visual-references")
    assert response.status_code == 200
    references = response.json()["references"]
    assert len(references) == 1
    assert references[0]["id"] == input_id
    assert references[0]["role"] == "颜色参考"
    assert references[0]["dimensions"] == ["style"]


@pytest.mark.skipif(os.environ.get("D2C_REAL_BUILD_TEST") != "1", reason="requires pnpm and a real dependency installation")
def test_bundle_asset_survives_real_build_and_nested_preview(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Synthetic archive and model output, real import, Vite build and preview server."""
    client = client_for(tmp_path, monkeypatch)
    response = client.post("/api/d2c/v1/design-inputs", json={"input_type": "figma_bundle", "content": bundle([
        ("src/App.tsx", b"export default 1"), ("public/images/logo.png", png())])})
    assert response.status_code == 200
    source = client.post("/api/d2c/v1/source-sets", json={"sources": [{"input_id": response.json()["input_id"]}]}).json()
    with storage.connect() as db:
        db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("run_bundle_real", source["source_set_id"], 1, "hash", "bundle-real", "hash", "BUILDING", storage.now(), storage.now()))
    settings = SimpleNamespace(runtime_dir=tmp_path, build_timeout=180, preview_host="127.0.0.1", preview_port_start=19380, preview_port_end=19400)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    files = runs.parse_files(json.dumps({"files": [
        {"path": "src/App.tsx", "content": 'import "./index.css"; export default function App() { return <div className="logo"/> }'},
        {"path": "src/index.css", "content": '.logo { background-image: url("./images/logo.png"); }'},
    ]}))
    assert runner.build_candidate("run_bundle_real", files)["status"] == "PASS"
    try:
        url = runner.preview_url("run_bundle_real", settings)
        with urllib.request.urlopen(url) as response:
            html = response.read().decode()
        css_path = re.search(r'href="([^\"]+\.css)"', html).group(1)
        with urllib.request.urlopen(urllib.parse.urljoin(url, css_path)) as response:
            css = response.read().decode()
        image_path = re.search(r'url\(["\']?([^"\')]+logo\.png)', css).group(1)
        with urllib.request.urlopen(urllib.parse.urljoin(urllib.parse.urljoin(url, css_path), image_path)) as response:
            assert response.headers.get_content_type() == "image/png"
            assert response.read() == png()
    finally:
        runner.close_previews()
