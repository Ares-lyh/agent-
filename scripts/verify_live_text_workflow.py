"""Exercise configured GPT planning and lyrics; stop before the approval gate."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.agents.master_agent import MasterAgent
from src.core.checkpoint import CheckpointManager
from src.services.llm_service import LLMService
from src.models.brief import Brief

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--workspace",type=Path,help="Reuse a prior verification directory without generating again")
    options=parser.parse_args()
    root=options.workspace or Path(tempfile.mkdtemp(prefix="music_live_text_"))
    model=LLMService(use_mock=False)
    brief=Brief(project_id="live_text_check",theme="毕业季告别，约定在下一个夏天相见",
                genre="流行摇滚",mood="温暖克制",duration_seconds=60,
                constraints=["中文歌词","原创"],lyrics_language="中文")
    master=MasterAgent(checkpoint_manager=CheckpointManager(str(root/"projects")),llm_service=model)
    try:
        cp,plan,lyrics=master.start(brief)
        print(json.dumps({"step":"planning_lyrics","model":model.model,"state":cp.state.value,
                          "plan_stages":len(plan.stages),"lyric_sections":len(lyrics.sections)},ensure_ascii=True),flush=True)
        print("LIVE_TEXT_WORKFLOW_OK; stopped at lyrics_ready; audio Agent was not called",flush=True)
        return 0
    except Exception as exc:
        print("LIVE_TEXT_WORKFLOW_FAILED "+type(exc).__name__,flush=True)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
