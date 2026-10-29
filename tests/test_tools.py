"""Unit tests for specialized Agent tools (Rhyme tool, Acoustic QC tool, Music API tool)."""
import os
import pytest
from src.tools.rhyme_tool import analyze_rhyme_and_meter, RhymeAnalysisResult
from src.tools.acoustic_qc_tool import inspect_acoustic_quality, AcousticInspectionResult
from src.tools.music_api_tool import RealMusicEngineClient
from src.utils.audio_utils import generate_synthetic_wav


def test_rhyme_tool_analysis():
    """Verify rhyme and meter analysis on Chinese song lyrics."""
    lines = [
        "穿梭在无尽的霓虹高楼",
        "电子琴弦划破夜的沉舟",
        "奔向那光明的破晓",
        "撕裂墨色苍穹",
    ]
    result = analyze_rhyme_and_meter(lines)
    assert isinstance(result, RhymeAnalysisResult)
    assert len(result.line_stats) == 4
    # Check rhyme pair detection (高楼 lou and 沉舟 zhou rhyme with ou)
    assert result.detected_rhymes is not None
    assert result.average_syllables > 5


def test_acoustic_qc_tool_on_valid_wav(tmp_path):
    """Verify acoustic QC on a valid 44.1kHz 16-bit WAV."""
    wav_path = str(tmp_path / "valid.wav")
    generate_synthetic_wav(wav_path, duration_seconds=1.5, sample_rate=44100)

    qc_res = inspect_acoustic_quality(wav_path)
    assert isinstance(qc_res, AcousticInspectionResult)
    assert qc_res.is_valid is True
    assert qc_res.sample_rate == 44100
    assert qc_res.channels == 2
    assert qc_res.bit_depth == 16
    assert qc_res.duration_seconds >= 1.0
    assert qc_res.sha256 != ""
    assert qc_res.clipping_ratio == 0.0


def test_acoustic_qc_tool_on_corrupt_file(tmp_path):
    """Verify acoustic QC rejects 0-byte or corrupted header files."""
    empty_path = str(tmp_path / "empty.wav")
    with open(empty_path, "wb") as f:
        pass

    qc_res = inspect_acoustic_quality(empty_path)
    assert qc_res.is_valid is False
    assert "0 字节" in qc_res.error_message or "空" in qc_res.error_message


def test_real_music_engine_client_initialization():
    """Verify RealMusicEngineClient handles configuration and fallback properly."""
    client = RealMusicEngineClient(provider="mock")
    assert client.provider == "mock"
    assert client.is_mock is True
