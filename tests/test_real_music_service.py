"""Music gateway failures never silently become synthesized success."""
import pytest
import requests
from unittest.mock import MagicMock
from src.services.real_music_service import RealMusicServiceAdapter
from src.tools.music_api_tool import RealMusicEngineClient
from src.core.exceptions import RateLimitExceededError, ModelTimeoutError, AudioCorruptedError
from src.utils.audio_utils import generate_synthetic_wav
from src.models.brief import Brief
from src.models.lyrics import Lyrics, LyricSection

@pytest.fixture
def sample_brief():
    return Brief(project_id="real_test",theme="海边",genre="流行",mood="温暖",duration_seconds=2)

@pytest.fixture
def sample_lyrics():
    return Lyrics(project_id="real_test",title="海",sections=[LyricSection(section_type="Verse",
        section_name="主歌",emotion_tag="温暖",lines=["海风吹来"])],structure_summary="Verse",raw_response_summary="test")

def test_no_key_requires_configuration(tmp_path,sample_brief,sample_lyrics):
    adapter=RealMusicServiceAdapter(provider="suno",api_key="")
    with pytest.raises(ValueError,match="未配置真实音乐服务"):
        adapter.generate("real_test",sample_brief,sample_lyrics,str(tmp_path/"audio.wav"))

def test_suno_api_call_success_with_mock_session(tmp_path,sample_brief,sample_lyrics):
    wave_path=tmp_path/"valid.wav"
    generate_synthetic_wav(str(wave_path),duration_seconds=2)
    response=MagicMock(status_code=200,content=wave_path.read_bytes(),headers={"content-type":"audio/wav"})
    session=MagicMock(spec=requests.Session)
    session.post.return_value=response
    adapter=RealMusicServiceAdapter(provider="suno",api_key="test-key",base_url="https://example.test",session=session)
    comp=adapter.generate("real_test",sample_brief,sample_lyrics,str(tmp_path/"out.wav"))
    assert comp.music_model_params.provider=="suno"
    assert not comp.music_model_params.is_mock

def test_429_rate_limit_triggers_error(tmp_path):
    session=MagicMock(spec=requests.Session)
    session.post.return_value=MagicMock(status_code=429)
    client=RealMusicEngineClient("suno","test","https://example.test",session=session)
    with pytest.raises(RateLimitExceededError):
        client.submit_and_wait("words","pop","warm",120,"C",2,str(tmp_path/"out.wav"))
    assert session.post.call_count==3

def test_timeout_triggers_model_timeout_error(tmp_path):
    session=MagicMock(spec=requests.Session)
    session.post.side_effect=requests.Timeout()
    client=RealMusicEngineClient("minimax","test","https://example.test",session=session)
    with pytest.raises(ModelTimeoutError):
        client.submit_and_wait("words","pop","warm",120,"C",2,str(tmp_path/"out.wav"))

def test_server_error_never_falls_back(tmp_path):
    session=MagicMock(spec=requests.Session)
    session.post.return_value=MagicMock(status_code=500)
    client=RealMusicEngineClient("gateway","test","https://example.test",session=session)
    with pytest.raises(ModelTimeoutError):
        client.submit_and_wait("words","pop","warm",120,"C",2,str(tmp_path/"out.wav"))
    assert not (tmp_path/"out.wav").exists()

def test_async_task_is_persisted_and_resumed_without_resubmit(tmp_path):
    source=tmp_path/"valid.wav"
    generate_synthetic_wav(str(source),duration_seconds=2)
    submitted=MagicMock(status_code=200,content=b"{}",headers={"content-type":"application/json"})
    submitted.json.return_value={"task_id":"remote-123"}
    poll=MagicMock(status_code=200)
    poll.json.return_value={"status":"completed","audio_url":"https://example.test/audio"}
    download=MagicMock(status_code=200)
    download.iter_content.return_value=[source.read_bytes()]
    session=MagicMock(spec=requests.Session)
    session.post.return_value=submitted
    session.get.side_effect=[poll,download]
    remembered=[]
    client=RealMusicEngineClient("gateway","test","https://example.test",session=session)
    result=client.submit_and_wait("words","pop","warm",120,"C",2,str(tmp_path/"out.wav"),
                                  on_task=remembered.append,idempotency_key="operation-1")
    assert remembered==["remote-123"]
    assert result.task_id=="remote-123"
    assert session.post.call_args.kwargs["headers"]["Idempotency-Key"]=="operation-1"
    session.get.side_effect=[poll,download]
    client.submit_and_wait("words","pop","warm",120,"C",2,str(tmp_path/"out2.wav"),task_id="remote-123")
    assert session.post.call_count==1

def test_mock_client_generates_valid_file(tmp_path):
    result=RealMusicEngineClient(provider="mock").submit_and_wait("words","pop","warm",120,"C",2,str(tmp_path/"out.wav"))
    assert result.provider=="mock"
    assert (tmp_path/"out.wav").read_bytes().startswith(b"RIFF")
