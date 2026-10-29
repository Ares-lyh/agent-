"""Tests for Lyrics Sub-Agent, version incrementing, and JSON error handling."""
import os
import json
import pytest
from src.models.brief import Brief
from src.agents.lyrics_agent import LyricsAgent
from src.services.llm_service import LLMService


def test_lyrics_generation_and_schema(temp_workspace):
    """Verify lyrics generation produces valid sections and markdown."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    llm = LLMService(use_mock=True)
    agent = LyricsAgent(llm_service=llm)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    lyrics = agent.generate(project_dir, brief, version="v1")
    assert lyrics.title == "盛夏的约号"
    assert len(lyrics.sections) >= 3
    assert lyrics.version == "v1"

    md = lyrics.to_markdown()
    assert "# 盛夏的约号" in md
    assert "[副歌]" in md


def test_scenario_3_lyrics_version_isolation(temp_workspace):
    """Scenario 3: 歌词版本不可覆盖，重复调用或修改生成自动自增版本 (v1 -> v2)."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    llm = LLMService(use_mock=True)
    agent = LyricsAgent(llm_service=llm)
    project_dir = os.path.join(temp_workspace["storage"], brief.project_id)

    # First generation -> v1
    l1 = agent.generate(project_dir, brief, version="v1")
    assert l1.version == "v1"
    v1_file = os.path.join(project_dir, "lyrics", "v1.json")
    assert os.path.exists(v1_file)

    # Save original v1 content
    with open(v1_file, "r", encoding="utf-8") as f:
        v1_content = f.read()

    # Second generation targeting v1 again -> should detect collision and increment to v2
    l2 = agent.generate(project_dir, brief, version="v1", feedback="加强副歌爆发力")
    assert l2.version == "v2"
    v2_file = os.path.join(project_dir, "lyrics", "v2.json")
    assert os.path.exists(v2_file)

    # Verify original v1 content was NOT overwritten
    with open(v1_file, "r", encoding="utf-8") as f:
        assert f.read() == v1_content


def test_scenario_4_deepseek_invalid_json_handling(temp_workspace):
    """Scenario 4: DeepSeek 返回非法 JSON 捕获并容错重试."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief = Brief.model_validate_json(f.read())

    # Simulate 1 invalid JSON attempt before succeeding
    llm = LLMService(use_mock=True, simulate_invalid_json_count=1)
    
    # First call will catch the malformed json exception and handle it
    with pytest.raises(json.JSONDecodeError):
        llm.generate_lyrics(brief, version="v1")

    # Second call (attempts >= simulate_count) recovers smoothly
    recovered_lyrics = llm.generate_lyrics(brief, version="v1")
    assert recovered_lyrics.title != ""
    assert len(recovered_lyrics.sections) > 0


def test_meter_tool_feedback_triggers_bounded_reflection(tmp_path):
    from src.models.lyrics import Lyrics, LyricSection
    class Generator:
        def __init__(self):
            self.feedback=[]
        def generate_lyrics(self,brief,version,feedback):
            self.feedback.append(feedback)
            lines=["风", "一二三四五六七八九十"] if len(self.feedback)==1 else ["一二三四五六七", "七六五四三二一"]
            return Lyrics(project_id=brief.project_id,version=version,title="测试",sections=[
                LyricSection(section_type="Verse",section_name="主歌",emotion_tag="温暖",lines=lines)],
                structure_summary="Verse",raw_response_summary="test")
    generator=Generator()
    brief=Brief(project_id="reflection",theme="风",genre="pop",mood="warm",duration_seconds=2)
    LyricsAgent(generator).generate(str(tmp_path),brief)
    assert len(generator.feedback)==2
    assert "词律工具" in generator.feedback[1]
