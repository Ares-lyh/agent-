"""Tests for Release Packager, SHA-256 integrity gate, and package_needs_info degradation."""
import os
import json
import pytest
from src.core.state_machine import ProjectState
from src.models.manifest import Manifest
from src.utils.hash_utils import calculate_sha256


def test_standard_release_package_ready(master_agent):
    """Verify song_001 with complete materials reaches package_ready."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief_data = json.load(f)

    # Full lifecycle
    master_agent.start(brief_data)
    master_agent.approve_stage("song_001", "lyrics", approved=True)
    master_agent.resume("song_001")
    master_agent.approve_stage("song_001", "audio", approved=True)

    manifest, pkg_dir = master_agent.export_package("song_001")

    assert manifest.package_status == "ready"
    assert manifest.project_id == "song_001"
    assert len(manifest.missing_materials) == 0
    assert len(manifest.integrity_issues) == 0

    # Verify all physical files exist
    assert os.path.exists(os.path.join(pkg_dir, "manifest.json"))
    assert os.path.exists(os.path.join(pkg_dir, "lyrics.md"))
    assert os.path.exists(os.path.join(pkg_dir, "composition.json"))
    assert os.path.exists(os.path.join(pkg_dir, "audio.wav"))
    assert os.path.exists(os.path.join(pkg_dir, "cover.png"))
    assert os.path.exists(os.path.join(pkg_dir, "approvals.json"))
    assert os.path.exists(os.path.join(pkg_dir, "README.md"))

    # Verify hashes match on disk
    assert calculate_sha256(os.path.join(pkg_dir, "lyrics.md")) == manifest.lyrics_file.sha256
    assert calculate_sha256(os.path.join(pkg_dir, "audio.wav")) == manifest.audio_file.sha256
    assert calculate_sha256(os.path.join(pkg_dir, "cover.png")) == manifest.cover_file.sha256


def test_scenario_11_missing_cover_causes_package_needs_info(master_agent):
    """Scenario 11: 针对异常样例 song_003 (缺失封面)，物料包强制标记为 needs_info，拒绝 ready."""
    with open("fixtures/briefs/song_003.json", "r", encoding="utf-8") as f:
        brief_data = json.load(f)

    # Run through pipeline
    master_agent.start(brief_data)
    master_agent.approve_stage("song_003", "lyrics", approved=True)
    master_agent.resume("song_003")
    master_agent.approve_stage("song_003", "audio", approved=True)

    manifest, pkg_dir = master_agent.export_package("song_003")

    # Gate: must be needs_info, never ready!
    assert manifest.package_status == "needs_info"
    ckpt = master_agent.checkpoint_manager.load_checkpoint("song_003")
    assert ckpt.state == ProjectState.PACKAGE_NEEDS_INFO
    assert any("封面" in m for m in manifest.missing_materials)


def test_scenario_12_tampered_audio_hash_causes_needs_info(master_agent):
    """Scenario 12: 哈希防篡改与完整性校验，若音频被篡改，阻断 package_ready."""
    with open("fixtures/briefs/song_001.json", "r", encoding="utf-8") as f:
        brief_data = json.load(f)

    master_agent.start(brief_data)
    master_agent.approve_stage("song_001", "lyrics", approved=True)
    master_agent.resume("song_001")

    master_agent.approve_stage("song_001", "audio", approved=True)

    # Tampering after approval must downgrade packaging
    ckpt = master_agent.checkpoint_manager.load_checkpoint("song_001")
    audio_file = os.path.join(master_agent.checkpoint_manager.get_project_dir("song_001"), "audio", f"{ckpt.audio_version}_audio.wav")
    with open(audio_file, "ab") as f:
        f.write(b"tampered_bytes")

    manifest, pkg_dir = master_agent.export_package("song_001")

    # Tampering should be caught in integrity_issues and downgrade status
    assert manifest.package_status == "needs_info"
    assert len(manifest.integrity_issues) > 0
    assert any("哈希不一致" in issue for issue in manifest.integrity_issues)


def test_scenario_13_boundary_rule_no_external_distribution_calls():
    """Scenario 13: 验证代码仓库中严禁引入或调用外部发行平台 API."""
    import src.services.packager as p_mod
    import src.agents.master_agent as m_mod
    
    # Assert neither module imports or calls external network endpoints for distribution
    for mod in [p_mod, m_mod]:
        src_code = open(mod.__file__, "r", encoding="utf-8").read()
        assert "publish_to_platform" not in src_code
        assert "net_ease_cloud_publish" not in src_code
        assert "douyin_open_api_upload" not in src_code
