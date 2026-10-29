"""Vocal requirements survive arrangement summarization and reach the actual gateway."""
import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import requests
from src.models.brief import Brief
from src.models.vocals import VocalRequirements, AudioGenerationIntent
from src.services.vocal_direction import resolve_vocals
from src.core.graph import brief_digest


def make_brief(**changes):
    return Brief(project_id="vocal_test", theme="鲲游向天空", genre="国风电子", mood="辽阔",
        duration_seconds=2, **changes)


@pytest.mark.parametrize("references,feedback,lead", [
    (["空灵女声"], None, "female"),
    (["female vocals"], "不要男声，必须全曲空灵女声独唱", "female"),
    (["空灵女声"], "空灵女声，但音频是男声", "female"),
    (["女声"], "空灵女声，不要男声主唱、男声念白或男女对唱", "female"),
    (["女声"], "不要女声，改为男声", "male"),
    (["女声"], "不要女声改为男声", "male"),
    (["男女对唱"], None, "mixed"),
    (["器乐和电子"], None, "unspecified"),
])
def test_resolver_does_not_treat_rejected_voice_as_requested_duet(references, feedback, lead):
    requirements = resolve_vocals(make_brief(references=references), feedback)
    assert requirements.lead == lead
    if "空灵" in "".join(references):
        assert "Ethereal" in requirements.instruction()


def test_explicit_vocal_contract_overrides_reference_but_can_be_refined_by_feedback():
    brief = make_brief(references=["男声"], vocals=VocalRequirements(lead="female", style="清澈"))
    assert resolve_vocals(brief).lead == "female"
    assert resolve_vocals(brief, "改为男声独唱").lead == "male"


def test_default_vocals_preserve_existing_checkpoint_brief_hash():
    brief = make_brief(references=["空灵女声"])
    old = brief.model_dump(exclude={"cover_placeholder_path", "vocals"})
    expected = hashlib.sha256(json.dumps(old, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert brief_digest(brief) == expected
    brief.vocals = VocalRequirements(lead="female")
    assert brief_digest(brief) != expected


def test_female_requirement_reaches_acemusic_even_when_arrangement_omits_it(master_agent, tmp_path):
    from src.agents.audio_agent import AudioAgent
    from src.tools.music_api_tool import RealMusicEngineClient
    from src.utils.audio_utils import generate_synthetic_wav
    brief = make_brief(references=["空灵女声"])
    cp, _, lyrics = master_agent.start(brief)
    master_agent.approve_stage(cp.project_id, "lyrics")
    folder = Path(master_agent.checkpoint_manager.get_project_dir(cp.project_id))
    source = tmp_path / "test-source.wav"
    generate_synthetic_wav(str(source), duration_seconds=2)
    session = MagicMock(spec=requests.Session)
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "voice-task", "model": "acemusic/acestep-v1.5-turbo",
        "choices": [{"message": {"role": "assistant", "audio": [{"type": "audio_url", "audio_url": {
            "url": "data:audio/wav;base64," + base64.b64encode(source.read_bytes()).decode()}}]}}]}
    session.post.return_value = response
    gateway = RealMusicEngineClient(provider="acemusic", api_key="test", base_url="https://example.test", session=session)
    agent = AudioAgent(music_model=gateway, llm_service=master_agent.llm_service)
    # The offline arrangement is generic; voice must come directly from the Brief.
    comp = agent.generate(str(folder), brief, lyrics, approval_ledger=master_agent.graph_engine.load(cp.project_id).approvals)
    submitted = session.post.call_args.kwargs["json"]
    caption = submitted["messages"][0]["content"]
    assert "Solo FEMALE lead" in caption and "Ethereal" in caption
    assert "全曲女声主唱" in caption
    assert "gender" not in submitted["audio_config"]  # No invented provider parameter.
    assert not submitted["audio_config"]["instrumental"]
    assert comp.vocal_requirements.lead == "female"
    intent = AudioGenerationIntent.model_validate_json((folder / "audio/.v1_generation-intent.json").read_text(encoding="utf-8"))
    assert intent.vocal_requirements == comp.vocal_requirements
    assert intent.prompt in caption
    assert submitted["lyrics"] == "\n\n".join("["+s.section_type+"]\n"+"\n".join(s.lines) for s in lyrics.sections)
