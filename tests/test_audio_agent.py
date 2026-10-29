"""Tests for Audio Sub-Agent, WAV inspection, retry backoff, and corruption handling."""
import os
import pytest
from src.models.brief import Brief
from src.models.approval import ApprovalLedger, ApprovalRecord
from src.utils.hash_utils import calculate_sha256
from pathlib import Path
from src.models.lyrics import Lyrics, LyricSection
from src.agents.audio_agent import AudioAgent
from src.services.mock_music_model import MockMusicModel
from src.core.exceptions import (
    AudioCorruptedError,
    RateLimitExceededError,
    WorkflowGateViolationError,
)
from src.utils.audio_utils import inspect_and_validate_wav


@pytest.fixture
def sample_lyrics():
    return Lyrics(
        project_id="song_001",
        version="v1",
        title="盛夏的约号",
        sections=[
            LyricSection(section_type="Verse", section_name="主歌", emotion_tag="温暖", lines=["歌词第1行"]),
            LyricSection(section_type="Chorus", section_name="副歌", emotion_tag="激动", lines=["副歌第1行"]),
        ],
        structure_summary="Verse-Chorus",
        raw_response_summary="test",
    )


def approved_lyrics(project_dir, lyrics):
    path=Path(project_dir)/"lyrics"/f"{lyrics.version}.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(lyrics.model_dump_json(indent=2),encoding="utf-8")
    record=ApprovalRecord(project_id=lyrics.project_id,stage="lyrics",approved=True,
        target_version=lyrics.version,artifact_sha256=calculate_sha256(str(path))).seal()
    return ApprovalLedger(project_id=lyrics.project_id,records=[record])


def test_audio_normal_generation_and_wav_headers(temp_workspace, sample_lyrics):
    """Verify normal generation produces valid PCM WAV with accurate headers."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    music_model = MockMusicModel(delay_seconds=0.0)
    agent = AudioAgent(music_model=music_model)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    comp = agent.generate(
        project_dir=project_dir,
        brief=brief,
        lyrics=sample_lyrics,
        version="v1",
        approval_ledger=approved_lyrics(project_dir, sample_lyrics),
    )

    assert comp.bpm > 60
    assert comp.key != ""
    assert os.path.exists(comp.audio_metadata.file_path)

    # Inspect WAV
    inspection = inspect_and_validate_wav(comp.audio_metadata.file_path)
    assert inspection.is_valid is True
    assert inspection.format == "wav"
    assert inspection.sample_rate == 44100
    assert inspection.channels == 2
    assert inspection.bit_depth == 16
    assert inspection.duration_seconds > 0
    assert inspection.file_size_bytes > 44
    assert inspection.sha256 == comp.audio_metadata.sha256


def test_scenario_2_and_6_empty_or_corrupt_audio_intercepted(temp_workspace, sample_lyrics):
    """Scenario 2 & 6: 音频为空或损坏被安全门禁拦截并抛错."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    # Empty file injection (0 bytes)
    empty_model = MockMusicModel(simulate_empty_file=True, delay_seconds=0.0)
    agent_empty = AudioAgent(music_model=empty_model)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    with pytest.raises(AudioCorruptedError) as exc_info:
        agent_empty.generate(project_dir, brief, sample_lyrics, "v1", approval_ledger=approved_lyrics(project_dir, sample_lyrics))
    assert "0 字节" in str(exc_info.value) or "空文件" in str(exc_info.value)

    # Corrupt header injection
    corrupt_model = MockMusicModel(simulate_corrupt_file=True, delay_seconds=0.0)
    agent_corrupt = AudioAgent(music_model=corrupt_model)
    with pytest.raises(AudioCorruptedError) as exc_info2:
        agent_corrupt.generate(project_dir, brief, sample_lyrics, "v2", approval_ledger=approved_lyrics(project_dir, sample_lyrics))
    assert "损坏" in str(exc_info2.value) or "过小" in str(exc_info2.value)


def test_scenario_3_audio_version_isolation(temp_workspace, sample_lyrics):
    """Scenario 3: 音频版本不可覆盖，重复调用自动自增版本 (v1 -> v2)."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    music_model = MockMusicModel(delay_seconds=0.0)
    agent = AudioAgent(music_model=music_model)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    # First generation -> v1
    c1 = agent.generate(project_dir, brief, sample_lyrics, "v1", approval_ledger=approved_lyrics(project_dir, sample_lyrics))
    assert c1.composition_version == "v1"
    v1_wav = os.path.join(project_dir, "audio", "v1_audio.wav")
    assert os.path.exists(v1_wav)
    v1_size = os.path.getsize(v1_wav)

    # Second generation targeting v1 again -> increments to v2
    c2 = agent.generate(project_dir, brief, sample_lyrics, "v1", approval_ledger=approved_lyrics(project_dir, sample_lyrics))
    assert c2.composition_version == "v2"
    v2_wav = os.path.join(project_dir, "audio", "v2_audio.wav")
    assert os.path.exists(v2_wav)

    # Verify original v1 file was untouched
    assert os.path.exists(v1_wav)
    assert os.path.getsize(v1_wav) == v1_size


def test_scenario_5_rate_limit_backoff_and_recovery(temp_workspace, sample_lyrics):
    """Scenario 5: 音乐模型 429 频控触发指数退避并在重试后成功恢复."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    # Simulate 2 rate limit occurrences, retry_with_backoff allows up to 3 tries
    music_model = MockMusicModel(simulate_429_count=2, delay_seconds=0.0)
    agent = AudioAgent(music_model=music_model)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    comp = agent.generate(project_dir, brief, sample_lyrics, "v1", approval_ledger=approved_lyrics(project_dir, sample_lyrics))
    assert comp is not None
    assert os.path.exists(comp.audio_metadata.file_path)


def test_unapproved_lyrics_gate(temp_workspace, sample_lyrics):
    """Scenario 1: 歌词未通过审核禁止调用音频生成."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    music_model = MockMusicModel(delay_seconds=0.0)
    agent = AudioAgent(music_model=music_model)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    with pytest.raises(WorkflowGateViolationError):
        agent.generate(project_dir, brief, sample_lyrics, "v1", is_lyrics_approved=False)
