"""Isolated HTTP lifecycle and immutable package tests."""
import io
import json
import zipfile
import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from src.core.state_machine import ProjectState

@pytest.fixture
def client(master_agent,monkeypatch):
    import src.web.app as web
    monkeypatch.setattr(web,"master",master_agent)
    monkeypatch.setattr(web,"ckpt_mgr",master_agent.checkpoint_manager)
    master_agent.start(json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8")))
    return TestClient(web.app)

def test_list_projects(client):
    response=client.get("/api/projects")
    assert response.status_code==200
    assert any(row["project_id"]=="song_001" for row in response.json())

def test_list_fixture_briefs(client):
    assert len(client.get("/api/fixtures/briefs").json())>=3

def test_get_project_detail(client):
    detail=client.get("/api/projects/song_001").json()
    assert detail["checkpoint"]["state"]=="lyrics_ready"
    assert not detail["has_audio"]

def test_stream_audio_endpoint(client):
    assert client.get("/api/projects/song_001/audio").status_code==404
    client.post("/api/projects/song_001/approve",json={"stage":"lyrics","approved":True})
    assert client.post("/api/projects/song_001/resume").status_code==200
    response=client.get("/api/projects/song_001/audio")
    assert response.status_code==200
    assert response.content.startswith(b"RIFF")

def test_create_and_lifecycle_via_web_api(client,tmp_path):
    brief=json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    brief["project_id"]="web_lifecycle"
    response=client.post("/api/projects/create",json={"brief":brief})
    assert response.status_code==200
    base="/api/projects/web_lifecycle"
    assert client.get(base+"/download/package").status_code==409
    assert client.post(base+"/approve",json={"stage":"audio","approved":False}).status_code==409
    assert client.post(base+"/approve",json={"stage":"lyrics","approved":True}).status_code==200
    assert client.post(base+"/resume").json()["state"]=="audio_ready"
    assert client.post(base+"/approve",json={"stage":"audio","approved":True}).status_code==200
    exported=client.post(base+"/export",json={"target_dir":str(tmp_path/"custom")})
    assert exported.json()["package_status"]=="ready"
    response=client.get(base+"/download/package")
    archive=zipfile.ZipFile(io.BytesIO(response.content))
    manifest=json.loads(archive.read("manifest.json"))
    assert manifest["project_id"]=="web_lifecycle"
    assert hashlib.sha256(archive.read("lyrics.md")).hexdigest()==manifest["lyrics_file"]["sha256"]
    before=client.get(base).json()["composition"]["audio_metadata"]["sha256"]
    response=client.post(base+"/audio/generate_full?duration=2")
    assert response.status_code==200
    assert response.json()["state"]=="audio_ready"
    assert client.get(base+"/download/package").status_code==409

def test_cover_upload_validates_image(client):
    response=client.post("/api/projects/song_001/cover/upload",files={"file":("cover.png",b"","image/png")})
    assert response.status_code==422

def test_package_tamper_blocks_download(client):
    base="/api/projects/song_001"
    client.post(base+"/approve",json={"stage":"lyrics","approved":True})
    client.post(base+"/resume")
    client.post(base+"/approve",json={"stage":"audio","approved":True})
    output=client.post(base+"/export",json={}).json()
    Path(output["package_dir"],"lyrics.md").write_text("changed",encoding="utf-8")
    assert client.get(base+"/download/package").status_code==409
    assert client.get(base).json()["checkpoint"]["state"]=="package_needs_info"


def test_studio_assets_and_rights_update(client):
    page=client.get("/")
    assert page.status_code==200
    assert 'id="rightsForm"' in page.text
    assert client.get("/static/app.js").status_code==200
    response=client.post("/api/projects/song_001/rights",json={"artist_name":"New Artist",
        "copyright_statement":"Original demo with no unlicensed samples", "rights_confirmed":True})
    assert response.status_code==200
    assert client.get("/api/projects/song_001").json()["brief"]["artist_name"]=="New Artist"
