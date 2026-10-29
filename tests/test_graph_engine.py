"""Unit and integration tests for LangGraph Multi-Agent Orchestration Engine."""
import os
import pytest
from src.core.graph import MusicGraphEngine
from src.core.state_machine import ProjectState
from src.core.checkpoint import CheckpointManager
from src.services.llm_service import LLMService
from src.services.mock_music_model import MockMusicModel
from src.agents.audio_agent import AudioAgent


@pytest.fixture
def test_engine(tmp_path):
    storage_dir = str(tmp_path / "storage")
    checkpoint_mgr = CheckpointManager(storage_dir)
    llm_service = LLMService(use_mock=True)
    # Use AudioAgent with mock model for deterministic testing
    audio_agent = AudioAgent(music_model=MockMusicModel())
    engine = MusicGraphEngine(
        checkpoint_manager=checkpoint_mgr,
        llm_service=llm_service,
        audio_agent=audio_agent,
    )
    return engine


def test_graph_initial_lifecycle_to_lyrics_ready(test_engine):
    """Test start() triggers plan_node and lyrics_node, then halts at lyrics_ready."""
    brief_data = {
        "project_id": "test_graph_001",
        "theme": "晨曦破晓，希望重燃",
        "genre": "流行摇滚",
        "mood": "激昂、励志",
        "duration_seconds": 2,
        "constraints": ["中文歌词", "副歌高亢"],
    }

    checkpoint, plan, lyrics = test_engine.start(brief_data)

    assert checkpoint.project_id == "test_graph_001"
    assert checkpoint.state == ProjectState.LYRICS_READY
    assert checkpoint.lyrics_version == "v1"
    assert plan.theme == "晨曦破晓，希望重燃"
    assert lyrics.title != ""
    assert len(lyrics.sections) >= 2


def test_graph_hitl_rejection_and_version_increment(test_engine):
    """Test human rejection on lyrics triggers version increment v1 -> v2."""
    brief_data = {
        "project_id": "test_graph_002",
        "theme": "落雨的街角",
        "genre": "民谣",
        "mood": "忧伤、释怀",
        "duration_seconds": 2,
    }

    checkpoint, plan, lyrics = test_engine.start(brief_data)
    assert checkpoint.lyrics_version == "v1"

    # Human rejects v1 lyrics
    updated_cp = test_engine.approve_stage(
        project_id="test_graph_002",
        stage="lyrics",
        approved=False,
        feedback="情绪过于悲伤，请增加释怀和温暖感",
        reviewer="Music Producer",
    )

    assert updated_cp.state == ProjectState.LYRICS_READY
    assert updated_cp.lyrics_version == "v2"


def test_graph_end_to_end_progression(test_engine):
    """Test complete flow: start -> approve lyrics -> resume (audio) -> approve audio -> resume (packaging)."""
    pid = "test_graph_e2e"
    brief_data = {
        "project_id": pid,
        "theme": "星辰大海的征途",
        "genre": "交响金属",
        "mood": "壮阔、豪迈",
        "duration_seconds": 2,
    }

    # 1. Start -> lyrics_ready
    cp, plan, lyrics = test_engine.start(brief_data)
    assert cp.state == ProjectState.LYRICS_READY

    # 2. Approve lyrics -> lyrics_approved
    cp_appr = test_engine.approve_stage(pid, stage="lyrics", approved=True)
    assert cp_appr.state == ProjectState.LYRICS_APPROVED

    # 3. Resume -> audio_ready
    cp_audio, msg = test_engine.resume(pid)
    assert cp_audio.state == ProjectState.AUDIO_READY
    assert "已完成作曲与音频生成" in msg

    # 4. Approve audio -> audio_approved
    cp_audio_appr = test_engine.approve_stage(pid, stage="audio", approved=True)
    assert cp_audio_appr.state == ProjectState.AUDIO_APPROVED

    # 5. Resume -> package_ready or package_needs_info
    cp_final, msg_final = test_engine.resume(pid)
    assert cp_final.state in (ProjectState.PACKAGE_READY, ProjectState.PACKAGE_NEEDS_INFO)
    assert "物料包构建完成" in msg_final
