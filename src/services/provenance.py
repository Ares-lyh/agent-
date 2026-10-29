"""Conservative source classification, including legacy mock synthesizers."""
from src.models.provenance import ArtifactProvenance


def artifact_provenance(artifact, stage):
    if artifact is None:
        return ArtifactProvenance(mode="missing", message="尚未生成")
    params = artifact.deepseek_params if stage == "lyrics" else artifact.music_model_params
    version = artifact.version if stage == "lyrics" else artifact.composition_version
    engines = " ".join(filter(None, (params.engine, params.model_engine, params.provider))).lower()
    if params.is_mock or "mock" in engines or "offline-demo" in engines:
        return ArtifactProvenance(mode="mock", provider="mock", model=params.model,
            version=version, message="离线演示：模板歌词" if stage == "lyrics" else "离线演示：本地合成音轨，非歌词演唱")
    if params.provider != "unknown" and params.model and (stage == "lyrics" or params.task_id):
        return ArtifactProvenance(mode="real", provider=params.provider, model=params.model,
            version=version, message="真实服务生成（已记录来源）")
    return ArtifactProvenance(mode="unknown", provider=params.provider, model=params.model,
        version=version, message="历史产物缺少来源记录，无法证明由真实服务生成")
