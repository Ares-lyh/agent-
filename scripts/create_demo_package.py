"""Build an explicit automated-acceptance example through CLI review commands."""
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["USE_MOCK_LLM"]="true"
    os.environ["MUSIC_PROVIDER"]="mock"
    project_id="acceptance_demo"
    from src.config import settings
    from src.services.packager import ReleasePackager
    from src.models.manifest import Manifest
    package_root=root/settings.PACKAGES_DIR/project_id
    existing=sorted(package_root.glob("v*/manifest.json"))
    if existing:
        path=max(existing,key=lambda p:int(p.parent.name[1:]))
        manifest=ReleasePackager().verify_package(str(path.parent),project_id,require_ready=True)
        print(path.parent)
        return 0
    brief=json.loads((root/"fixtures/briefs/song_001.json").read_text(encoding="utf-8"))
    brief.update(project_id=project_id,duration_seconds=8,duration_text="8秒",
                 artist_name="自动化验收示例（非商业歌曲）",
                 copyright_statement="自动化验收用模板歌词和合成和弦示例，不代表真实歌曲或商业版权确认。",
                 rights_confirmed=True,
                 cover_placeholder_path=str((root/"fixtures/covers/cover_01.png").resolve()))
    brief_path=root/"fixtures/briefs/acceptance_demo.json"
    brief_path.write_text(json.dumps(brief,ensure_ascii=False,indent=2),encoding="utf-8")
    commands=[
        ["run","--brief",str(brief_path)],
        ["approve","--project",project_id,"--stage","lyrics","--reviewer","Automated Acceptance Demo"],
        ["resume",project_id],
        ["approve","--project",project_id,"--stage","audio","--reviewer","Automated Acceptance Demo"],
        ["export","--project",project_id]]
    for command in commands:
        subprocess.run([sys.executable,"-m","src.cli",*command],check=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
