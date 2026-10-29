from src.models.lyrics import Lyrics
from src.models.composition import Composition
from src.models.common import GenerationParameters
from src.services.provenance import artifact_provenance


def test_legacy_mock_marker_is_never_treated_as_real(master_agent):
    import json
    from pathlib import Path
    brief = json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    cp, _, lyrics = master_agent.start(brief)
    lyrics.deepseek_params = GenerationParameters(engine="deepseek-v3-orchestrator")
    assert artifact_provenance(lyrics, "lyrics").mode == "unknown"
    lyrics.deepseek_params = GenerationParameters(provider="configured-text-api", model="real-text-model")
    assert artifact_provenance(lyrics, "lyrics").mode == "real"
    master_agent.approve_stage(cp.project_id, "lyrics")
    cp, _ = master_agent.resume(cp.project_id)
    comp = master_agent._load_latest_composition(cp.project_id, cp.composition_version)
    comp.music_model_params = GenerationParameters(model_engine="mock-music-synthesizer-v1")
    assert not comp.music_model_params.is_mock  # Historical records lacked this boolean.
    assert artifact_provenance(comp, "audio").mode == "mock"
