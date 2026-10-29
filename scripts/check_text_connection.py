"""Read .env and verify the configured text model without printing credentials."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.services.llm_service import LLMService

def main():
    service=LLMService(use_mock=False)
    print(json.dumps({"model":service.model,"host":urlparse(service.base_url).hostname,
                      "api_key_configured":bool(service.api_key)},ensure_ascii=True),flush=True)
    try:
        text=service._call_deepseek_with_retry(
            "Return a JSON object with a single field status whose string value is connected.",
            "Verify JSON output for a music creation application.",max_retries=1)
        result=json.loads(text)
        if result.get("status")!="connected":
            raise ValueError("unexpected structured response")
        print("TEXT_MODEL_CONNECTION_OK",flush=True)
        return 0
    except Exception as exc:
        # Provider exceptions can carry request context. Never echo response bodies or headers.
        print("TEXT_MODEL_CONNECTION_FAILED "+type(exc).__name__,flush=True)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
