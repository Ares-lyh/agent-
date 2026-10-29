"""Persisted graph interrupts and business transaction crash windows."""
import json
from pathlib import Path
import pytest
from src.agents.master_agent import MasterAgent
from src.services.llm_service import LLMService
from src.services.mock_music_model import MockMusicModel
from src.core.state_machine import ProjectState
from src.core.exceptions import WorkflowGateViolationError
from src.models.workflow import MusicGraphState

def brief():
    data=json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    data["project_id"]="durable"
    return data

def restart(master):
    return MasterAgent(checkpoint_manager=master.checkpoint_manager,llm_service=LLMService(use_mock=True),
                       music_model=MockMusicModel(delay_seconds=0),packager=master.packager)

def test_native_interrupt_is_durable_and_cannot_approve(master_agent):
    master_agent.start(brief())
    config={"configurable":{"thread_id":"durable"}}
    assert any(task.interrupts for task in master_agent.graph_engine.graph.get_state(config).tasks)
    new=restart(master_agent)
    assert any(task.interrupts for task in new.graph_engine.graph.get_state(config).tasks)
    with pytest.raises(WorkflowGateViolationError):
        new.graph_engine._node_audio(MusicGraphState(project_id="durable"))
    cp,_=new.resume("durable")
    assert cp.state==ProjectState.LYRICS_READY
    new.approve_stage("durable","lyrics")
    assert new.resume("durable")[0].state==ProjectState.AUDIO_READY

def test_plan_publication_before_checkpoint_crash_recovers(master_agent,monkeypatch):
    save=master_agent.checkpoint_manager.save_checkpoint
    failed=[False]
    def crash(cp):
        if "plan_generation" in cp.completed_stages and not failed[0]:
            failed[0]=True
            raise RuntimeError("plan checkpoint crash")
        return save(cp)
    monkeypatch.setattr(master_agent.checkpoint_manager,"save_checkpoint",crash)
    with pytest.raises(RuntimeError):
        master_agent.start(brief())
    cp,_=restart(master_agent).resume("durable")
    assert cp.state==ProjectState.LYRICS_READY
    assert "plan_generation" in cp.completed_stages

def test_input_mirror_missing_can_recover_from_initial_checkpoint(master_agent,monkeypatch):
    import src.core.graph as module
    original=module.atomic_write
    def crash(path,content):
        if Path(path).name=="brief.json":
            raise OSError("brief mirror crash")
        return original(path,content)
    monkeypatch.setattr(module,"atomic_write",crash)
    with pytest.raises(OSError):
        master_agent.start(brief())
    assert master_agent.checkpoint_manager.project_exists("durable")
    monkeypatch.setattr(module,"atomic_write",original)
    cp,_=restart(master_agent).resume("durable")
    assert cp.state==ProjectState.LYRICS_READY

def test_package_rename_before_checkpoint_crash_reuses_same_package(master_agent,monkeypatch):
    master_agent.start(brief()); master_agent.approve_stage("durable","lyrics")
    master_agent.resume("durable"); master_agent.approve_stage("durable","audio")
    save=master_agent.checkpoint_manager.save_checkpoint
    failed=[False]
    def crash(cp):
        if cp.state==ProjectState.PACKAGE_READY and not failed[0]:
            failed[0]=True
            raise RuntimeError("package commit crash")
        return save(cp)
    monkeypatch.setattr(master_agent.checkpoint_manager,"save_checkpoint",crash)
    with pytest.raises(RuntimeError):
        master_agent.export_package("durable")
    new=restart(master_agent)
    cp,_=new.resume("durable")
    assert cp.state==ProjectState.PACKAGE_READY
    assert cp.package_version=="v1"
    assert not Path(new.packager.output_root,"durable","v2").exists()


def test_audio_published_before_comp_json_can_recover(master_agent,monkeypatch):
    import src.agents.audio_agent as module
    master_agent.start(brief()); master_agent.approve_stage("durable","lyrics")
    original=module.publish
    failed=[False]
    def crash(source,destination):
        if str(destination).endswith("_comp.json") and not failed[0]:
            failed[0]=True
            raise RuntimeError("audio publication crash")
        return original(source,destination)
    monkeypatch.setattr(module,"publish",crash)
    with pytest.raises(RuntimeError):
        master_agent.resume("durable")
    cp,_=restart(master_agent).resume("durable")
    assert cp.audio_version=="v1"
    assert cp.state==ProjectState.AUDIO_READY


def test_metadata_commit_is_recoverable(master_agent,monkeypatch):
    import src.core.graph as module
    master_agent.start(brief())
    updated=master_agent._load_brief("durable")
    updated.artist_name="new artist"
    original=module.atomic_write
    def crash(path,content):
        if Path(path).name=="brief.json":
            raise OSError("metadata mirror crash")
        return original(path,content)
    monkeypatch.setattr(module,"atomic_write",crash)
    with pytest.raises(OSError):
        master_agent.graph_engine.update_metadata("durable",updated,"RIGHTS","test update")
    monkeypatch.setattr(module,"atomic_write",original)
    new=restart(master_agent)
    new.resume("durable")
    assert new._load_brief("durable").artist_name=="new artist"
    assert not new.checkpoint_manager.load_checkpoint("durable").brief_mirror_pending
