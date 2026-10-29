"""Tests for system optimizations: CoT JSON parsing, lock reentrancy, auto-fix, and rhyme improvements."""
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from src.services.llm_service import LLMService
from src.utils.persistence import project_lock, publish, atomic_write
from src.tools.rhyme_tool import analyze_rhyme_and_meter
from src.models.brief import Brief
import src.web.app as web


def test_cot_and_thinking_json_parsing():
    service = LLMService(use_mock=True)
    # 1. DeepSeek-R1 thinking tag
    r1_output = """<think>
    Thinking about the music brief...
    The user wants a pop rock song for graduation.
    I should structure the JSON with title and sections.
    </think>
    ```json
    {
        "title": "青春不散场",
        "structure_summary": "Verse-Chorus",
        "sections": []
    }
    ```"""
    parsed = service._clean_and_parse_json(r1_output)
    assert parsed["title"] == "青春不散场"

    # 2. Conversational prefix and suffix
    chat_output = """这是为您生成的任务计划 JSON：
    ```
    {
        "bpm": 128,
        "key": "G Major"
    }
    ```
    希望这份方案符合您的预期！"""
    parsed2 = service._clean_and_parse_json(chat_output)
    assert parsed2["bpm"] == 128
    assert parsed2["key"] == "G Major"

    # 3. Leading text without code blocks
    leading_text = """Result: {"status": "success", "score": 98}"""
    parsed3 = service._clean_and_parse_json(leading_text)
    assert parsed3["status"] == "success"
    assert parsed3["score"] == 98


def test_project_lock_reentrancy(tmp_path):
    lock_dir = tmp_path / "lock_test"
    # Nested lock in the same thread must succeed without deadlocking
    with project_lock(lock_dir):
        with project_lock(lock_dir):
            test_file = lock_dir / "test.txt"
            test_file.write_text("reentrant success", encoding="utf-8")
            assert test_file.read_text(encoding="utf-8") == "reentrant success"


def test_publish_atomic_replacement(tmp_path):
    source = tmp_path / "part.txt"
    dest = tmp_path / "final.txt"
    source.write_text("hello atomic", encoding="utf-8")
    dest.write_text("old content", encoding="utf-8")
    publish(source, dest)
    assert dest.read_text(encoding="utf-8") == "hello atomic"
    assert not source.exists()


def test_rhyme_tool_with_modal_particles_and_english():
    # Chinese with modal particle "吧" and "啊"
    lines = [
        "走廊的风吹翻泛黄的时光吧",
        "无论身在何方我们终会再遇上啊",
    ]
    res = analyze_rhyme_and_meter(lines)
    assert len(res.line_stats) == 2
    # Both 光 (guang -> ang) and 上 (shang -> ang) share the 'ang' family despite trailing '吧'/'啊'
    assert res.line_stats[0].rhyme_vowel == "ang"
    assert res.line_stats[1].rhyme_vowel == "ang"

    # English endings
    eng_lines = [
        "Walking through the neon night",
        "Everything will be alright",
    ]
    eng_res = analyze_rhyme_and_meter(eng_lines)
    assert eng_res.line_stats[0].rhyme_vowel == "ai"
    assert eng_res.line_stats[1].rhyme_vowel == "ai"


def test_brief_auto_fix_endpoint(master_agent, monkeypatch, tmp_path):
    monkeypatch.setattr(web, "master", master_agent)
    monkeypatch.setattr(web, "ckpt_mgr", master_agent.checkpoint_manager)
    client = TestClient(web.app)

    # Use song_003 which has anomalies (duration conflict, primary platform, missing cover)
    raw = json.loads(Path("fixtures/briefs/song_003.json").read_text(encoding="utf-8"))
    raw["project_id"] = "autofix_test"
    raw["duration_seconds"] = 120
    raw["duration_text"] = "3分钟"  # conflict with 120s
    raw["platform"] = ["网易云音乐"]
    raw["primary_platform"] = "QQ音乐"  # not in platform
    raw["cover_placeholder_path"] = None  # missing cover

    client.post("/api/projects/create", json={"brief": raw})
    detail_before = client.get("/api/projects/autofix_test").json()
    assert len(detail_before["checkpoint"]["detected_anomalies"]) >= 2

    # Call auto-fix
    fix_res = client.post("/api/projects/autofix_test/brief/auto-fix")
    assert fix_res.status_code == 200
    assert "时长展示对齐" in fix_res.json()["message"]
    assert "QQ音乐" in fix_res.json()["message"]
    assert "封面" in fix_res.json()["message"]

    detail_after = client.get("/api/projects/autofix_test").json()
    assert detail_after["brief"]["duration_text"] == "2分钟"
    assert "QQ音乐" in detail_after["brief"]["platform"]
    assert detail_after["brief"]["cover_placeholder_path"] is not None
    assert Path(detail_after["brief"]["cover_placeholder_path"]).is_file()
