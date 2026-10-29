"""Regression coverage for all reproducible business review failures."""
import json
import io
import struct
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from src.core.state_machine import ProjectState
from src.core.exceptions import WorkflowGateViolationError
from src.models.lyrics import Lyrics
from src.models.approval import ApprovalLedger
from src.models.brief import Brief
from src.services.llm_service import LLMService
from src.utils.audio_utils import inspect_and_validate_wav
from src.tools.acoustic_qc_tool import inspect_acoustic_quality
from src.utils.hash_utils import calculate_sha256

def brief(pid="regression"):
    result=json.loads(Path("fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    result["project_id"]=pid
    return result

def through_audio(master,pid="regression"):
    master.start(brief(pid))
    master.approve_stage(pid,"lyrics")
    master.resume(pid)
    return pid

def approved_audio(master,pid="regression"):
    through_audio(master,pid)
    master.approve_stage(pid,"audio")
    return pid

def test_rejection_cannot_start_audio_before_lyrics_approved(master_agent):
    master_agent.start(brief())
    with pytest.raises(WorkflowGateViolationError):
        master_agent.approve_stage("regression","audio",False)
    assert not (Path(master_agent.checkpoint_manager.get_project_dir("regression"))/"audio").exists()

def test_third_lyrics_generation_preserves_approved_history(master_agent):
    master_agent.start(brief())
    master_agent.approve_stage("regression","lyrics",False,feedback="更温暖")
    master_agent.approve_stage("regression","lyrics")
    directory=Path(master_agent.checkpoint_manager.get_project_dir("regression"))
    before=(directory/"lyrics/v2.json").read_bytes()
    lyric=master_agent.lyrics_agent.generate(str(directory),Brief.model_validate(brief()),"v1",feedback="全新故事")
    assert lyric.version=="v3"
    assert (directory/"lyrics/v2.json").read_bytes()==before

def test_third_audio_generation_preserves_history(master_agent):
    through_audio(master_agent)
    master_agent.approve_stage("regression","audio",False,feedback="减半速度")
    directory=Path(master_agent.checkpoint_manager.get_project_dir("regression"))
    before=(directory/"audio/v2_audio.wav").read_bytes()
    lyrics=master_agent._load_latest_lyrics("regression","v1")
    comp=master_agent.audio_agent.generate(str(directory),Brief.model_validate(brief()),lyrics,"v1",
        approval_ledger=master_agent.graph_engine.load("regression").approvals,feedback="更温暖")
    assert comp.composition_version=="v3"
    assert (directory/"audio/v2_audio.wav").read_bytes()==before

def test_audio_feedback_changes_output_and_is_recorded(master_agent):
    through_audio(master_agent)
    first=master_agent._load_latest_composition("regression","v1")
    master_agent.approve_stage("regression","audio",False,feedback="减半速度，移除打击乐")
    second=master_agent._load_latest_composition("regression","v2")
    assert second.audio_metadata.sha256!=first.audio_metadata.sha256
    assert second.bpm<first.bpm
    assert "减半" in second.music_model_params.feedback

def test_crash_during_initial_lyrics_can_resume(master_agent,monkeypatch):
    original=master_agent.lyrics_agent.generate
    def fail(*args,**kwargs):
        raise RuntimeError("crashed")
    monkeypatch.setattr(master_agent.lyrics_agent,"generate",fail)
    with pytest.raises(RuntimeError):
        master_agent.start(brief())
    cp=master_agent.checkpoint_manager.load_checkpoint("regression")
    assert cp.state==ProjectState.NEW
    assert cp.pending.stage=="lyrics"
    assert cp.last_error=="crashed"
    monkeypatch.setattr(master_agent.lyrics_agent,"generate",original)
    cp,_=master_agent.resume("regression")
    assert cp.state==ProjectState.LYRICS_READY

def test_crash_after_audio_publication_reuses_same_version(master_agent,monkeypatch):
    master_agent.start(brief()); master_agent.approve_stage("regression","lyrics")
    save=master_agent.checkpoint_manager.save_checkpoint
    failed=[False]
    def crash(cp):
        if cp.state==ProjectState.AUDIO_READY and not failed[0]:
            failed[0]=True
            raise RuntimeError("crash after publication")
        save(cp)
    monkeypatch.setattr(master_agent.checkpoint_manager,"save_checkpoint",crash)
    with pytest.raises(RuntimeError):
        master_agent.resume("regression")
    cp,_=master_agent.resume("regression")
    directory=Path(master_agent.checkpoint_manager.get_project_dir("regression"))
    assert cp.audio_version=="v1"
    assert list((directory/"audio").glob("*_comp.json"))==[directory/"audio/v1_comp.json"]

def test_failed_rejection_retains_feedback_for_resume(master_agent,monkeypatch):
    through_audio(master_agent)
    original=master_agent.audio_agent.generate
    def fail(*args,**kwargs):
        raise RuntimeError("temporary failure")
    monkeypatch.setattr(master_agent.audio_agent,"generate",fail)
    with pytest.raises(RuntimeError):
        master_agent.approve_stage("regression","audio",False,feedback="减半速度")
    cp=master_agent.checkpoint_manager.load_checkpoint("regression")
    assert cp.pending.version=="v2"
    assert cp.pending.feedback=="减半速度"
    assert not cp.approvals.get_latest_record("audio").approved
    monkeypatch.setattr(master_agent.audio_agent,"generate",original)
    cp,_=master_agent.resume("regression")
    assert cp.audio_version=="v2"
    assert master_agent._load_latest_composition("regression","v2").music_model_params.feedback=="减半速度"

@pytest.mark.parametrize("mutation",["lyrics","approval_version","empty_cover","missing_copyright","missing_composition","missing_lyrics","missing_audio"])
def test_bad_materials_are_never_ready(master_agent,mutation):
    approved_audio(master_agent)
    directory=Path(master_agent.checkpoint_manager.get_project_dir("regression"))
    if mutation=="lyrics":
        path=directory/"lyrics/v1.json"
        lyrics=Lyrics.model_validate_json(path.read_text(encoding="utf-8"))
        lyrics.sections[0].lines[0]="changed after approval"
        path.write_text(lyrics.model_dump_json(),encoding="utf-8")
    elif mutation=="approval_version":
        cp=master_agent.graph_engine.load("regression")
        cp.approvals.records[-1].target_version="v999"
        master_agent.graph_engine.save(cp)
    elif mutation in ("empty_cover","missing_copyright"):
        b=master_agent._load_brief("regression")
        if mutation=="empty_cover":
            cover=directory/"empty.png"; cover.write_bytes(b""); b.cover_placeholder_path=str(cover)
        else:
            b.copyright_statement=None
        (directory/"brief.json").write_text(b.model_dump_json(),encoding="utf-8")
    else:
        target={"missing_composition":"audio/v1_comp.json","missing_lyrics":"lyrics/v1.json","missing_audio":"audio/v1_audio.wav"}[mutation]
        (directory/target).unlink()
    manifest,_=master_agent.export_package("regression")
    assert manifest.package_status=="needs_info"
    assert master_agent.checkpoint_manager.load_checkpoint("regression").state==ProjectState.PACKAGE_NEEDS_INFO

def test_ready_package_can_degrade_and_history_survives(master_agent):
    approved_audio(master_agent)
    first,path=master_agent.export_package("regression")
    directory=Path(master_agent.checkpoint_manager.get_project_dir("regression"))
    with (directory/"audio/v1_audio.wav").open("ab") as stream:
        stream.write(b"changed")
    second,newpath=master_agent.export_package("regression")
    assert second.package_status=="needs_info"
    assert Path(path,"manifest.json").is_file()
    assert path!=newpath
    assert second.package_version=="v2"
    assert master_agent.checkpoint_manager.load_checkpoint("regression").state==ProjectState.PACKAGE_NEEDS_INFO

def test_changed_brief_is_conflict(master_agent):
    master_agent.start(brief())
    changed=brief(); changed["theme"]="another theme"
    with pytest.raises(ValueError,match="已改变"):
        master_agent.start(changed)

def test_parallel_start_is_idempotent(master_agent):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:master_agent.start(brief()),range(2)))
    assert all(result[0].lyrics_version=="v1" for result in results)
    directory=Path(master_agent.checkpoint_manager.get_project_dir("regression"))
    assert len(list((directory/"lyrics").glob("v*.json")))==1

@pytest.mark.parametrize("kind",["zero_frames","truncated","clipped","silent","bad_rate"])
def test_qc_rejects_incomplete_and_bad_signal(tmp_path,kind):
    path=tmp_path/"quality.wav"
    with wave.open(str(path),"wb") as stream:
        stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(8000 if kind=="bad_rate" else 44100)
        value=32767 if kind=="clipped" else 0 if kind=="silent" else 1000
        stream.writeframes(b"" if kind=="zero_frames" else struct.pack("<hh",value,value)*44100)
    if kind=="truncated":
        path.write_bytes(path.read_bytes()[:84])
    assert not inspect_acoustic_quality(str(path)).is_valid

def test_real_provider_selected_without_mock_injection(master_agent,monkeypatch):
    from src.config import settings
    from src.agents.master_agent import MasterAgent
    from src.tools.music_api_tool import RealMusicEngineClient
    monkeypatch.setattr(settings,"MUSIC_PROVIDER","suno")
    master=MasterAgent(checkpoint_manager=master_agent.checkpoint_manager,llm_service=LLMService(use_mock=True))
    assert isinstance(master.audio_agent.client,RealMusicEngineClient)
    assert not master.audio_agent.client.is_mock

def test_failed_llm_never_silently_returns_template(monkeypatch):
    service=LLMService(api_key="test",use_mock=False)
    def fail(*args,**kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(service,"_call_deepseek_with_retry",fail)
    monkeypatch.setattr("src.services.llm_service.time.sleep",lambda _:None)
    with pytest.raises(RuntimeError,match="provider down"):
        service.generate_lyrics(Brief.model_validate(brief()))
    with pytest.raises(RuntimeError,match="provider down"):
        service.generate_task_plan(Brief.model_validate(brief()))
