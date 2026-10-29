"""Services are imported lazily so the text client has no graph dependency."""
__all__ = ["MockMusicModel", "LLMService", "ReleasePackager", "RunReport", "ExecutionEvent"]

def __getattr__(name):
    if name == "MockMusicModel":
        from src.services.mock_music_model import MockMusicModel
        return MockMusicModel
    if name == "LLMService":
        from src.services.llm_service import LLMService
        return LLMService
    if name == "ReleasePackager":
        from src.services.packager import ReleasePackager
        return ReleasePackager
    if name in ("RunReport", "ExecutionEvent"):
        from src.services.reporter import RunReport, ExecutionEvent
        return {"RunReport":RunReport,"ExecutionEvent":ExecutionEvent}[name]
    raise AttributeError(name)
