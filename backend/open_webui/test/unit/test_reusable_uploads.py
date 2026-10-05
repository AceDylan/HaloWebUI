import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from open_webui.models import files as files_model
from open_webui.models.files import File, FileModel, Files
from open_webui.routers import files
from open_webui.utils.auth import get_verified_user

DIGEST = hashlib.sha256(b"same bytes").hexdigest()


@pytest.fixture
def table(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'files.db'}")
    File.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(files_model, "get_db", get_db)

    def add(id, *, user="u1", name="a.png", created_at=1, path=None, **meta):
        stored = tmp_path / f"{id}_{name}"
        stored.write_bytes(b"same bytes")
        meta = {
            "name": name,
            "size": 10,
            "sha256": DIGEST,
            "upload_process": False,
            "processing_mode": "retrieval",
            **meta,
        }
        with get_db() as db:
            db.add(
                File(
                    id=id,
                    user_id=user,
                    filename=name,
                    path=path or str(stored),
                    meta={k: v for k, v in meta.items() if v is not None},
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            db.commit()

    return add


def find(name=None, process=False, size=10, user="u1", mode="retrieval"):
    found = Files.get_reusable_upload(user, DIGEST, size, process, mode, name=name)
    return found.id if found else None


def test_finds_the_newest_finished_upload_and_prefers_the_same_name(table):
    table("old", created_at=1)
    table("new", name="b.png", created_at=2)
    assert find() == "new"
    assert find(name="a.png") == "old"


def test_only_matches_uploads_stored_the_same_way(table):
    table("unfinished", sha256=None)  # no digest yet: still uploading or failed
    table("other-user", user="u2")
    table("processed", upload_process=True, processing_mode="full_context")
    table("gone", path="/nonexistent/upload.png")
    assert find() is None
    assert find(size=11) is None
    assert find(process=True) is None
    assert find(process=True, mode="full_context") == "processed"


@pytest.fixture
def client(monkeypatch, tmp_path):
    app = FastAPI()
    app.state.config = SimpleNamespace(
        ALLOWED_FILE_EXTENSIONS=[], FILE_PROCESSING_DEFAULT_MODE="retrieval"
    )
    owner = SimpleNamespace(id="upload-owner", role="user")
    app.dependency_overrides[get_verified_user] = lambda: owner
    app.include_router(files.router, prefix="/files")
    records, meta_updates = {}, []

    def store(stream, filename):
        path = tmp_path / filename
        data = stream.read()
        path.write_bytes(data)
        return len(data), str(path)

    def insert(user_id, form):
        record = FileModel(
            **form.model_dump(), user_id=user_id, created_at=1, updated_at=1
        )
        records[record.id] = record
        return record

    monkeypatch.setattr(files.Storage, "upload_file", store)
    monkeypatch.setattr(files.Files, "insert_new_file", insert)
    monkeypatch.setattr(files.Files, "get_file_by_id", records.get)
    monkeypatch.setattr(
        files.Files,
        "update_file_metadata_by_id",
        lambda id, meta: meta_updates.append((id, meta)) or records.get(id),
    )
    with TestClient(app) as test_client:
        yield test_client, records, meta_updates


def test_reusable_upload_records_the_digest_of_the_stored_bytes(client):
    test_client, records, meta_updates = client
    response = test_client.post(
        "/files/?process=false&reuse=true",
        files={"file": ("a.png", b"same bytes", "image/png")},
    )
    assert response.status_code == 200
    file_id = response.json()["id"]
    assert meta_updates == [(file_id, {"sha256": DIGEST, "upload_process": False})]
    with open(records[file_id].path, "rb") as stored:
        assert stored.read() == b"same bytes"


def test_plain_upload_is_not_reusable(client):
    test_client, _, meta_updates = client
    response = test_client.post(
        "/files/?process=false", files={"file": ("a.png", b"same bytes", "image/png")}
    )
    assert response.status_code == 200
    assert meta_updates == []


def test_lookup_endpoint_asks_for_the_resolved_mode(client, monkeypatch):
    test_client, _, _ = client
    calls = []
    monkeypatch.setattr(
        files.Files,
        "get_reusable_upload",
        lambda *args, **kwargs: calls.append((args, kwargs)) or None,
    )
    response = test_client.get(
        f"/files/reusable?sha256={DIGEST}&size=10&name=../a.png&process=true"
    )
    assert response.status_code == 200
    assert response.json() is None
    assert calls == [
        (("upload-owner", DIGEST, 10, True, "retrieval"), {"name": "a.png"})
    ]
    assert test_client.get("/files/reusable?sha256=nothex&size=1").status_code == 422
