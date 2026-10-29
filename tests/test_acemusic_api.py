"""Native music completions, exact lyrics, response recovery and conversion."""
import base64
import json
import subprocess
import requests
from unittest.mock import MagicMock
import pytest
from src.core.exceptions import AudioCorruptedError, ModelTimeoutError, RateLimitExceededError
from src.tools.music_api_tool import RealMusicEngineClient
from src.utils.audio_utils import generate_synthetic_wav, inspect_and_validate_wav


def client(session):
    return RealMusicEngineClient(provider="acemusic", api_key="test-credential",
        base_url="https://api.acemusic.ai", session=session)


def completion(content, model="acemusic/acestep-v1.5-turbo", finish="stop"):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "id": "chatcmpl-music-test", "object": "chat.completion", "created": 1700000000,
        "model": model, "choices": [{"index": 0, "finish_reason": finish, "message": {
            "role": "assistant", "content": "Music generated successfully.",
            "audio": [{"type": "audio_url", "audio_url": {"url": content}}]}}],
        "usage": {"total_tokens": 10}}
    return response


def run(instance, path, **kwargs):
    return instance.submit_and_wait("清新的吉他流行编曲", "流行", "温暖", 120, "C Major",
        2, str(path), lyrics="[Verse]\n海风吹过远方", vocal_language="中文", **kwargs)


def test_native_request_preserves_approved_lyrics_and_decodes_audio(tmp_path):
    source = tmp_path / "source.wav"
    generate_synthetic_wav(str(source), duration_seconds=2)
    url = "data:audio/wav;base64," + base64.b64encode(source.read_bytes()).decode()
    session = MagicMock(spec=requests.Session)
    session.post.return_value = completion(url)
    remembered = []
    result = run(client(session), tmp_path / "out.wav", on_task=remembered.append,
                 idempotency_key="operation-123")
    assert session.post.call_args.args[0] == "https://api.acemusic.ai/v1/chat/completions"
    request = session.post.call_args.kwargs["json"]
    assert request["model"] == "acemusic/acestep-v1.5-turbo"
    assert request["lyrics"] == "[Verse]\n海风吹过远方"
    assert request["audio_config"] == {"duration": 2.0, "format": "wav", "bpm": 120,
        "key_scale": "C Major", "vocal_language": "zh", "instrumental": False}
    assert not request["sample_mode"] and not request["use_format"]
    assert not request["use_cot_caption"] and not request["use_cot_language"]
    assert remembered == ["acemusic:pending:operation-123", "chatcmpl-music-test"]
    assert result.provider == "acemusic"
    assert (tmp_path / "out.wav").read_bytes() == source.read_bytes()
    assert session.post.call_args.kwargs["allow_redirects"] is False
    assert "Idempotency-Key" not in session.post.call_args.kwargs["headers"]


def test_cached_completed_response_recovers_without_resubmission(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    generate_synthetic_wav(str(source), duration_seconds=2)
    session = MagicMock(spec=requests.Session)
    session.post.return_value = completion("data:audio/wav;base64," + base64.b64encode(source.read_bytes()).decode())
    instance = client(session)
    original = instance._convert
    def interrupted(*args):
        raise AudioCorruptedError("transcoder interrupted")
    monkeypatch.setattr(instance, "_convert", interrupted)
    with pytest.raises(AudioCorruptedError):
        run(instance, tmp_path / "out.wav", idempotency_key="op")
    monkeypatch.setattr(instance, "_convert", original)
    result = run(instance, tmp_path / "out.wav", task_id="chatcmpl-music-test")
    assert result.task_id == "chatcmpl-music-test"
    assert session.post.call_count == 1


def test_uncertain_sync_timeout_never_automatically_resubmits(tmp_path):
    session = MagicMock(spec=requests.Session)
    session.post.side_effect = requests.Timeout()
    remembered = []
    with pytest.raises(ModelTimeoutError):
        run(client(session), tmp_path / "out.wav", on_task=remembered.append, idempotency_key="op")
    assert remembered == ["acemusic:pending:op"]
    with pytest.raises(ModelTimeoutError, match="避免重复生成"):
        run(client(session), tmp_path / "out.wav", task_id=remembered[0])
    assert session.post.call_count == 1


@pytest.mark.parametrize("status", [401, 429, 500])
def test_rejections_never_become_mock_success_or_leak_body(tmp_path, status):
    session = MagicMock(spec=requests.Session)
    session.post.return_value = MagicMock(status_code=status, text="private-provider-payload")
    remembered = []
    with pytest.raises((AudioCorruptedError, RateLimitExceededError, ModelTimeoutError)) as error:
        run(client(session), tmp_path / "out.wav", on_task=remembered.append)
    assert "private-provider-payload" not in str(error.value)
    assert "test-credential" not in str(error.value)
    assert session.post.call_count == 1
    assert not (tmp_path / "out.wav").exists()
    assert remembered[-1] is None if status in (401, 429) else remembered[-1] is not None


@pytest.mark.parametrize("url", ["data:audio/wav;base64,invalid!", "data:text/plain;base64,eA==", "data:audio/wav;base64,"])
def test_invalid_base64_or_mime_is_rejected(tmp_path, url):
    session = MagicMock(spec=requests.Session)
    session.post.return_value = completion(url)
    with pytest.raises(AudioCorruptedError):
        run(client(session), tmp_path / "out.wav")
    assert not (tmp_path / "out.wav").exists()


def test_real_mp3_transcodes_with_bundled_ffmpeg(tmp_path, monkeypatch):
    import imageio_ffmpeg
    from src.config import settings
    monkeypatch.setattr(settings, "FFMPEG_PATH", "ffmpeg")
    monkeypatch.setattr("src.tools.music_api_tool.shutil.which", lambda _: None)
    source = tmp_path / "source.wav"
    compressed = tmp_path / "source.mp3"
    generate_synthetic_wav(str(source), duration_seconds=2)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(source),
                    "-c:a", "libmp3lame", str(compressed)], check=True, capture_output=True)
    session = MagicMock(spec=requests.Session)
    session.post.return_value = completion("data:audio/mpeg;base64," + base64.b64encode(compressed.read_bytes()).decode())
    run(client(session), tmp_path / "out.wav")
    inspected = inspect_and_validate_wav(str(tmp_path / "out.wav"))
    assert inspected.is_valid and inspected.sample_rate == 44100 and inspected.channels == 2
    assert abs(inspected.duration_seconds - 2) < .1


def test_missing_lyrics_does_not_invoke_remote_model(tmp_path):
    session = MagicMock(spec=requests.Session)
    with pytest.raises(ValueError, match="纯歌词"):
        client(session).submit_and_wait("caption", "pop", "warm", 120, "C", 2, str(tmp_path / "out.wav"))
    session.post.assert_not_called()


def test_http_audio_return_does_not_forward_api_key(tmp_path):
    source = tmp_path / "source.wav"
    generate_synthetic_wav(str(source), duration_seconds=2)
    session = MagicMock(spec=requests.Session)
    session.post.return_value = completion("https://files.acemusic.ai/test.wav")
    download = MagicMock(status_code=200)
    download.iter_content.return_value = [source.read_bytes()]
    session.get.return_value = download
    run(client(session), tmp_path / "out.wav")
    assert "headers" not in session.get.call_args.kwargs


def test_base_url_with_v1_is_not_duplicated(tmp_path):
    session = MagicMock(spec=requests.Session)
    session.post.return_value = MagicMock(status_code=401)
    instance = client(session)
    instance.base_url += "/v1/"
    with pytest.raises(AudioCorruptedError):
        run(instance, tmp_path / "out.wav")
    assert session.post.call_args.args[0] == "https://api.acemusic.ai/v1/chat/completions"


def test_audio_agent_native_flow_uses_bound_lyrics_and_real_provider(master_agent):
    from pathlib import Path
    from src.models.brief import Brief
    from src.models.lyrics import Lyrics
    from src.agents.audio_agent import AudioAgent
    brief_data = json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    master_agent.start(brief_data)
    master_agent.approve_stage("song_001", "lyrics")
    directory = Path(master_agent.checkpoint_manager.get_project_dir("song_001"))
    approved = Lyrics.model_validate_json((directory / "lyrics/v1.json").read_text(encoding="utf-8"))
    generated = directory / "test-response.wav"
    generate_synthetic_wav(str(generated), duration_seconds=2)
    session = MagicMock(spec=requests.Session)
    session.post.return_value = completion("data:audio/wav;base64," + base64.b64encode(generated.read_bytes()).decode())
    agent = AudioAgent(music_model=client(session), llm_service=master_agent.llm_service)
    composition = agent.generate(str(directory), Brief.model_validate(brief_data), approved,
        approval_ledger=master_agent.graph_engine.load("song_001").approvals,
        operation_id="test-native-operation")
    assert composition.music_model_params.provider == "acemusic"
    assert composition.music_model_params.model == "acemusic/acestep-v1.5-turbo"
    assert not composition.music_model_params.is_mock
    assert composition.lyrics_version == "v1"
    submitted = session.post.call_args.kwargs["json"]
    assert submitted["lyrics"] == "\n\n".join("[" + section.section_type + "]\n" + "\n".join(section.lines)
                                                for section in approved.sections)
    assert "# " + approved.title not in submitted["messages"][0]["content"]
    assert composition.audio_metadata.file_size_bytes > 44
