"""Every test runs with fresh storage and explicit offline providers."""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
import pytest

workspace_root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(workspace_root))
from src.config import settings
from src.core.checkpoint import CheckpointManager
from src.services.llm_service import LLMService
from src.services.mock_music_model import MockMusicModel
from src.services.packager import ReleasePackager
from src.agents.master_agent import MasterAgent

@pytest.fixture(autouse=True)
def isolate_business_files(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(workspace_root/"fixtures",tmp_path/"fixtures")
    for path in (tmp_path/"fixtures/briefs").glob("*.json"):
        data=json.loads(path.read_text(encoding="utf-8"))
        data["duration_seconds"]=2
        data["duration_text"]="2秒"
        path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    monkeypatch.setattr(settings,"BASE_STORAGE_DIR",str(tmp_path/"projects"))
    monkeypatch.setattr(settings,"PACKAGES_DIR",str(tmp_path/"packages"))
    monkeypatch.setattr(settings,"USE_MOCK_LLM",True)
    monkeypatch.setattr(settings,"MUSIC_PROVIDER","mock")
    monkeypatch.setattr(settings,"MOCK_AUDIO_SAMPLE_DURATION",0)
    monkeypatch.setenv("USE_MOCK_LLM","true")
    monkeypatch.setenv("MUSIC_PROVIDER","mock")

@pytest.fixture
def temp_workspace(tmp_path):
    return {"root":str(tmp_path),"storage":str(tmp_path/"projects"),"packages":str(tmp_path/"packages")}

@pytest.fixture
def master_agent(temp_workspace):
    return MasterAgent(CheckpointManager(temp_workspace["storage"]),LLMService(use_mock=True),
                       MockMusicModel(delay_seconds=0),ReleasePackager(temp_workspace["packages"]))
