"""Tests for brief validation, parsing, and anomaly detection."""
import json
import pytest
from pathlib import Path
ORIGINAL_FIXTURES = Path(__file__).resolve().parents[1]/"fixtures/briefs"
from src.models.brief import Brief, BriefAnomaly


def test_song_001_normal_brief():
    """Verify song_001 parses cleanly with 0 anomalies."""
    with open(ORIGINAL_FIXTURES/"song_001.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    brief = Brief.model_validate(data)
    anomalies = brief.detect_anomalies()
    assert brief.project_id == "song_001"
    assert brief.duration_seconds == 210
    assert brief.parse_duration_text() == 210
    assert len(anomalies) == 0


def test_song_002_normal_brief():
    """Verify song_002 parses cleanly with 0 anomalies."""
    with open(ORIGINAL_FIXTURES/"song_002.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    brief = Brief.model_validate(data)
    anomalies = brief.detect_anomalies()
    assert brief.project_id == "song_002"
    assert brief.duration_seconds == 180
    assert brief.parse_duration_text() == 180
    assert len(anomalies) == 0


def test_song_003_anomalies_detection():
    """Verify song_003 accurately captures all 3 required anomalies:
    1. duration_seconds (210s) vs duration_text ("2分45秒" = 165s) conflict
    2. primary_platform ('QQ音乐') not in platform list (['网易云音乐', '抖音'])
    3. missing cover_placeholder_path
    """
    with open(ORIGINAL_FIXTURES/"song_003.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    brief = Brief.model_validate(data)
    anomalies = brief.detect_anomalies()
    assert brief.project_id == "song_003"
    assert len(anomalies) == 3

    anomaly_fields = {a.field: a for a in anomalies}
    assert "duration" in anomaly_fields
    assert anomaly_fields["duration"].issue_type == "conflict"
    assert "210" in anomaly_fields["duration"].message
    assert "165" in anomaly_fields["duration"].message

    assert "primary_platform" in anomaly_fields
    assert anomaly_fields["primary_platform"].issue_type == "inconsistency"
    assert "QQ音乐" in anomaly_fields["primary_platform"].message

    assert "cover_placeholder_path" in anomaly_fields
    assert anomaly_fields["cover_placeholder_path"].issue_type == "missing"
