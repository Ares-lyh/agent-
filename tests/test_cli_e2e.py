"""End-to-End CLI lifecycle integration tests."""
import os
import shutil
from click.testing import CliRunner
from src.cli import cli
from src.config import settings


def test_cli_full_lifecycle(monkeypatch):
    """Verify complete CLI run -> status -> approve lyrics -> resume -> approve audio -> export."""
    monkeypatch.setattr(settings, "USE_MOCK_LLM", True)
    # Ensure clean state for song_001
    song_dir = os.path.join(settings.BASE_STORAGE_DIR, "song_001")
    if os.path.exists(song_dir):
        shutil.rmtree(song_dir, ignore_errors=True)

    runner = CliRunner()

    # 1. Run brief
    res_run = runner.invoke(cli, ["run", "--brief", "fixtures/briefs/song_001.json"])
    assert res_run.exit_code == 0
    assert "项目初始化成功" in res_run.output or "盛夏的约号" in res_run.output

    # 2. Status
    res_status = runner.invoke(cli, ["status", "song_001"])
    assert res_status.exit_code == 0
    assert "song_001" in res_status.output
    assert "lyrics_ready" in res_status.output

    # 3. Approve Lyrics
    res_app_lyrics = runner.invoke(cli, ["approve", "--project", "song_001", "--stage", "lyrics"])
    assert res_app_lyrics.exit_code == 0
    assert "审核批准通过" in res_app_lyrics.output

    # 4. Resume to trigger audio generation
    res_res1 = runner.invoke(cli, ["resume", "song_001"])
    assert res_res1.exit_code == 0
    assert "audio_ready" in res_res1.output

    # 5. Approve Audio
    res_app_audio = runner.invoke(cli, ["approve", "--project", "song_001", "--stage", "audio"])
    assert res_app_audio.exit_code == 0
    assert "audio_approved" in res_app_audio.output

    # 6. Export Release Package
    res_export = runner.invoke(cli, ["export", "--project", "song_001", "--out", "release-package"])
    assert res_export.exit_code == 0
    assert "物料包导出完成" in res_export.output
    assert "ready" in res_export.output
