"""Observe slow/failing workflows through HTTP without approving generated content."""
import json
from pathlib import Path
from threading import Event
import pytest
from fastapi.testclient import TestClient
from src.models.api import ProviderStatus, RuntimeStatus
from src.web.jobs import StudioJobs


@pytest.fixture
def async_studio(master_agent, monkeypatch):
    import src.web.app as web
    jobs = StudioJobs()
    monkeypatch.setattr(web, "master", master_agent)
    monkeypatch.setattr(web, "ckpt_mgr", master_agent.checkpoint_manager)
    monkeypatch.setattr(web, "studio_jobs", jobs)
    ready = RuntimeStatus(text=ProviderStatus(mode="real", provider="test", configured=True),
        music=ProviderStatus(mode="real", provider="test", configured=True), production_ready=True, message="test")
    monkeypatch.setattr(web, "runtime_status", lambda: ready)
    brief = json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    brief["project_id"] = "async_studio"
    yield TestClient(web.app), master_agent, jobs, brief
    jobs.executor.shutdown(wait=True)


def test_async_start_returns_durable_progress_and_deduplicates(async_studio, monkeypatch):
    client, master, jobs, brief = async_studio
    entered, release = Event(), Event()
    original = master.llm_service.generate_task_plan
    calls = []
    def slow_plan(req):
        calls.append(req.project_id)
        entered.set()
        assert release.wait(10), "test must release the controlled provider"
        return original(req)
    monkeypatch.setattr(master.llm_service, "generate_task_plan", slow_plan)
    try:
        response = client.post("/api/projects/start", json={"brief": brief})
        assert response.status_code == 202
        assert entered.wait(5)
        cp = master.graph_engine.load(brief["project_id"])
        assert cp.pending.stage == "lyrics" and cp.state.value == "new"
        assert client.get("/api/projects/async_studio/progress").json()["phase"] == "plan"
        assert client.post("/api/projects/start", json={"brief": brief}).status_code == 202
        changed = {**brief, "theme": "changed"}
        assert client.post("/api/projects/start", json={"brief": changed}).status_code == 409
        assert calls == ["async_studio"]
        assert client.post("/api/projects/async_studio/approve", json={"stage": "audio", "approved": True}).status_code == 409
    finally:
        release.set()
    jobs.futures["async_studio"].result(timeout=10)
    progress = client.get("/api/projects/async_studio/progress").json()
    assert progress["state"] == "lyrics_ready" and progress["execution_status"] == "idle"
    detail = client.get("/api/projects/async_studio").json()
    assert detail["approvals"] == [] and not detail["has_audio"]


def test_async_failure_is_visible_and_original_transaction_can_resume(async_studio, monkeypatch):
    client, master, jobs, brief = async_studio
    original = master.llm_service.generate_task_plan
    def fail(req):
        raise RuntimeError("文本模型请求失败 (HTTP 503)")
    monkeypatch.setattr(master.llm_service, "generate_task_plan", fail)
    assert client.post("/api/projects/start", json={"brief": brief}).status_code == 202
    with pytest.raises(RuntimeError):
        jobs.futures["async_studio"].result(timeout=10)
    progress = client.get("/api/projects/async_studio/progress").json()
    assert progress["execution_status"] == "failed"
    assert "503" in progress["last_error"]
    operation = master.graph_engine.load("async_studio").pending.operation_id
    monkeypatch.setattr(master.llm_service, "generate_task_plan", original)
    assert client.post("/api/projects/async_studio/execute").status_code == 202
    jobs.futures["async_studio"].result(timeout=10)
    cp = master.graph_engine.load("async_studio")
    assert cp.state.value == "lyrics_ready" and cp.pending is None
    assert cp.lyrics_version == "v1" and cp.approvals.records == []
    assert operation


def test_restart_reports_pending_transaction_as_interrupted(async_studio):
    client, master, jobs, brief = async_studio
    master.graph_engine.prepare_start(brief)
    progress = client.get("/api/projects/async_studio/progress").json()
    assert progress["execution_status"] == "interrupted"
    assert "恢复" in progress["message"]


def test_web_start_rejects_demo_configuration(master_agent, monkeypatch):
    import src.web.app as web
    monkeypatch.setattr(web, "master", master_agent)
    monkeypatch.setattr(web, "ckpt_mgr", master_agent.checkpoint_manager)
    client = TestClient(web.app)
    status = client.get("/api/runtime").json()
    assert not status["production_ready"] and status["text"]["mode"] == "mock"
    assert "api_key" not in json.dumps(status).lower()
    brief = json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    assert client.post("/api/projects/start", json={"brief": brief}).status_code == 409
    assert not master_agent.checkpoint_manager.project_exists(brief["project_id"])


def test_async_execute_preserves_both_human_review_gates(async_studio):
    client, master, jobs, brief = async_studio
    client.post("/api/projects/start", json={"brief": brief})
    jobs.futures["async_studio"].result(timeout=10)
    # Execute while lyrics await review must not call the audio provider.
    client.post("/api/projects/async_studio/execute")
    jobs.futures["async_studio"].result(timeout=10)
    assert not client.get("/api/projects/async_studio").json()["has_audio"]
    assert client.post("/api/projects/async_studio/approve",
        json={"stage": "lyrics", "approved": True}).status_code == 200
    client.post("/api/projects/async_studio/execute")
    jobs.futures["async_studio"].result(timeout=10)
    detail = client.get("/api/projects/async_studio").json()
    assert detail["checkpoint"]["state"] == "audio_ready" and detail["has_audio"]
    assert len(detail["approvals"]) == 1
    client.post("/api/projects/async_studio/execute")
    jobs.futures["async_studio"].result(timeout=10)
    assert client.post("/api/projects/async_studio/export", json={}).status_code == 409


def test_queued_audio_progress_does_not_claim_to_wait_for_lyrics_review(async_studio, monkeypatch):
    client, master, jobs, brief = async_studio
    master.start(brief)
    master.approve_stage("async_studio", "lyrics")
    monkeypatch.setattr(jobs, "status", lambda _: "queued")
    progress = client.get("/api/projects/async_studio/progress").json()
    assert progress["phase"] == "audio" and progress["execution_status"] == "queued"
