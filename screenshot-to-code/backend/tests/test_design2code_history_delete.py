from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from design2code import storage
from design2code.routes import router


def test_delete_history_is_atomic_and_retains_files(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(runtime_dir=tmp_path))
    finished, active = "run_" + "a" * 32, "run_" + "b" * 32
    with storage.connect() as db:
        for run_id, status in ((finished, "READY_FOR_REVIEW"), (active, "BUILDING")):
            db.execute("INSERT INTO runs (id,set_id,revision,source_hash,idempotency_key,request_hash,status,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (run_id, "set", 1, "hash", run_id, "hash", status, '{"files":[]}', storage.now(), storage.now()))
        db.execute("INSERT INTO run_events VALUES (?,?,?,?,?)", (finished, 1, "CREATED", "{}", storage.now()))
    artifact = tmp_path / "runs" / finished / "example.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("preserved")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.post('/api/d2c/v1/runs/delete-history', json={'run_ids': [finished, active]}).status_code == 409
    assert client.get(f'/api/d2c/v1/runs/{finished}').status_code == 200
    assert client.post('/api/d2c/v1/runs/delete-history', json={'run_ids': [finished]}).status_code == 200
    assert client.get(f'/api/d2c/v1/runs/{finished}').status_code == 404
    assert [item['run_id'] for item in client.get('/api/d2c/v1/runs').json()['runs']] == [active]
    assert artifact.read_text() == 'preserved'
    with storage.connect() as db:
        row = db.execute('SELECT status, result_json, idempotency_key FROM runs WHERE id=?', (finished,)).fetchone()
        assert row['status'] == 'DELETED' and row['result_json'] is None and row['idempotency_key'] == finished
        assert db.execute('SELECT 1 FROM run_events WHERE run_id=?', (finished,)).fetchone() is None
