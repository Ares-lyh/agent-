"""GPT-compatible envelopes, bounded retries and schema enforcement."""
import json
from unittest.mock import MagicMock
import pytest
from src.services.llm_service import LLMService
from src.models.brief import Brief

def response(status,content=None,text=""):
    item=MagicMock(status_code=status,text=text)
    item.json.return_value={"choices":[{"message":{"role":"assistant","content":content}}]}
    return item

def test_configured_model_and_json_request_are_preserved(monkeypatch):
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return response(200,'{"status":"ok"}')
    monkeypatch.setattr("requests.post",post)
    service=LLMService(api_key="test",base_url="https://example.test/v1",model="gpt-6.1-sol",use_mock=False)
    assert service._call_deepseek_with_retry("system","user")=='{"status":"ok"}'
    assert calls[0][0]=="https://example.test/v1/chat/completions"
    assert calls[0][1]["json"]["model"]=="gpt-6.1-sol"

def test_only_unsupported_parameter_is_removed(monkeypatch):
    replies=iter([response(400,text="temperature unsupported"),response(200,'{}')])
    payloads=[]
    def post(url,**kwargs):
        payloads.append(kwargs["json"])
        return next(replies)
    monkeypatch.setattr("requests.post",post)
    service=LLMService(api_key="test",use_mock=False)
    assert service._call_deepseek_with_retry("system","user")=="{}"
    assert "temperature" not in payloads[1]
    assert "response_format" in payloads[1]

def test_http_failures_do_not_leak_provider_body(monkeypatch):
    monkeypatch.setattr("requests.post",lambda *a,**k:response(401,text="secret-provider-body"))
    with pytest.raises(RuntimeError,match="HTTP 401") as exc:
        LLMService(api_key="test",use_mock=False)._call_deepseek_with_retry("s","u")
    assert "secret-provider-body" not in str(exc.value)

def test_illegal_plan_output_is_rejected(monkeypatch):
    service=LLMService(api_key="test",use_mock=False)
    monkeypatch.setattr(service,"_call_deepseek_with_retry",lambda *a,**k:'{"stages":[]}')
    with pytest.raises(RuntimeError,match="结构校验"):
        service.generate_task_plan(Brief(project_id="plan_test",theme="theme",genre="pop",mood="warm",duration_seconds=2))


def composition_inputs():
    from src.models.lyrics import Lyrics, LyricSection
    brief = Brief(project_id="composition_test", theme="海天", genre="国风电子", mood="辽阔", duration_seconds=180)
    lyrics = Lyrics(project_id=brief.project_id, title="海天", structure_summary="Verse-Chorus",
        sections=[LyricSection(section_type="Verse", section_name="主歌一", emotion_tag="静", lines=["海向天"]),
                  LyricSection(section_type="Chorus", section_name="副歌", emotion_tag="动", lines=["风向前"])],
        raw_response_summary="isolated test")
    return brief, lyrics


def test_composition_normalizes_validated_provider_prose_without_losing_content(monkeypatch):
    brief, lyrics = composition_inputs()
    service = LLMService(api_key="test", use_mock=False)
    valid = {"bpm": 120, "key": "D Minor", "arrangement_notes": "电子与古筝",
        "section_arrangements": [{"section_name": s.section_name, "emotion": s.emotion_tag,
                                  "instrumentation": "古筝、鼓"} for s in lyrics.sections]}
    provider = {**valid, "arrangement_notes": ["电子铺底", "古筝点缀"],
        "section_arrangements": [{"section_name": s.section_name, "emotion": [s.emotion_tag],
                                  "instrumentation": ["古筝", "鼓"]} for s in lyrics.sections]}
    calls = []
    def complete(system, user):
        calls.append((system, user))
        return json.dumps(provider)
    monkeypatch.setattr(service, "_call_deepseek_with_retry", complete)
    plan = service.generate_composition_plan(brief, lyrics)
    assert plan.arrangement_notes == "电子铺底；古筝点缀"
    assert all(section.instrumentation == "古筝；鼓" for section in plan.section_arrangements)
    assert len(calls) == 1
    assert '"$defs"' in calls[0][0]  # Actual Pydantic schema, including the section type.
    assert "arrangement_notes" in calls[0][0]


def test_composition_rejects_untyped_prose_and_supplies_field_feedback(monkeypatch):
    brief, lyrics = composition_inputs()
    service = LLMService(api_key="test", use_mock=False)
    valid = {"bpm": 120, "key": "D Minor", "arrangement_notes": "电子与古筝",
        "section_arrangements": [{"section_name": s.section_name, "emotion": s.emotion_tag,
                                  "instrumentation": "古筝、鼓"} for s in lyrics.sections]}
    replies = iter([json.dumps({**valid, "arrangement_notes": [{"untrusted_extra": "object must not pass"}]}), json.dumps(valid)])
    calls = []
    def complete(system, user):
        calls.append((system, user))
        return next(replies)
    monkeypatch.setattr(service, "_call_deepseek_with_retry", complete)
    assert service.generate_composition_plan(brief, lyrics).arrangement_notes == "电子与古筝"
    assert len(calls) == 2
    assert "arrangement_notes" in calls[1][1] and "string_type" in calls[1][1]
    assert "object must not pass" not in calls[1][1]


def test_composition_rejects_persistently_invalid_sections_without_mock_fallback(monkeypatch):
    brief, lyrics = composition_inputs()
    service = LLMService(api_key="test", use_mock=False)
    calls = []
    def complete(*args):
        calls.append(args)
        return json.dumps({"bpm": 120, "key": "D Minor", "arrangement_notes": "arrangement",
            "section_arrangements": [{"section_name": "wrong section", "emotion": "warm", "instrumentation": "strings"}]})
    monkeypatch.setattr(service, "_call_deepseek_with_retry", complete)
    with pytest.raises(RuntimeError, match="段落校验"):
        service.generate_composition_plan(brief, lyrics)
    assert len(calls) == 3
