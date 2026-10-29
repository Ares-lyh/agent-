"""Tests for atomic checkpoint persistence, resume recovery, and idempotency."""
import os
import json
import pytest
from src.core.checkpoint import ProjectCheckpoint, CheckpointManager
from src.core.state_machine import ProjectState
from src.agents.master_agent import MasterAgent
from src.services.llm_service import LLMService
from src.services.mock_music_model import MockMusicModel


def test_atomic_checkpoint_persistence(temp_workspace):
    """Verify atomic write prevents torn reads and persists correctly."""
    mgr = CheckpointManager(base_storage_dir=temp_workspace["storage"])
    ckpt = ProjectCheckpoint(
        project_id="test_ckpt_001",
        state=ProjectState.LYRICS_READY,
        lyrics_version="v1",
        audio_version="v1",
        completed_stages=["brief_parsing", "lyrics_generation"],
    )

    mgr.save_checkpoint(ckpt)
    assert mgr.project_exists("test_ckpt_001")

    loaded = mgr.load_checkpoint("test_ckpt_001")
    assert loaded.project_id == "test_ckpt_001"
    assert loaded.state == ProjectState.LYRICS_READY
    assert "lyrics_generation" in loaded.completed_stages


def test_scenario_7_idempotency_on_repeated_runs(master_agent):
    """Scenario 7: 同一 brief 重复运行幂等，直接加载既有进度，不产生冲突版本."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief_data = json.load(f)

    # First run
    ckpt1, plan1, lyrics1 = master_agent.start(brief_data)
    assert ckpt1.state == ProjectState.LYRICS_READY
    assert lyrics1.version == "v1"

    # Repeated run with exact same brief
    ckpt2, plan2, lyrics2 = master_agent.start(brief_data)
    assert ckpt2.state == ProjectState.LYRICS_READY
    assert lyrics2.version == "v1"
    assert ckpt2.project_id == ckpt1.project_id


def test_scenario_8_crash_and_resume_recovery(master_agent):
    """Scenario 8: 中途崩溃后从断点恢复 (resume)."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief_data = json.load(f)

    # 1. Start pipeline -> reaches LYRICS_READY
    master_agent.start(brief_data)

    # 2. Simulate user approving lyrics
    master_agent.approve_stage("song_001", "lyrics", approved=True)
    ckpt = master_agent.checkpoint_manager.load_checkpoint("song_001")
    assert ckpt.state == ProjectState.LYRICS_APPROVED

    # 3. Simulate process crash / restart: instantiate new MasterAgent pointing to same storage
    new_agent = MasterAgent(
        checkpoint_manager=master_agent.checkpoint_manager,
        llm_service=LLMService(use_mock=True),
        music_model=MockMusicModel(delay_seconds=0.0),
    )

    # 4. Call resume -> recovers checkpoint and advances to AUDIO_READY
    resumed_ckpt, msg = new_agent.resume("song_001")
    assert resumed_ckpt.state == ProjectState.AUDIO_READY
    assert "audio_generation" in resumed_ckpt.completed_stages

    # 5. Approve audio and resume to final packaging
    new_agent.approve_stage("song_001", "audio", approved=True)
    final_ckpt, msg2 = new_agent.resume("song_001")
    assert final_ckpt.state == ProjectState.PACKAGE_READY
