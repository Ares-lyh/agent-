"""Read-only music authentication/model check. Never creates a song."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.models.acemusic import ModelsResponse
from src.tools.music_api_tool import RealMusicEngineClient


def main():
    client = RealMusicEngineClient()
    try:
        client.validate_configuration()
        if client.provider != "acemusic":
            raise ValueError("this check expects ACEMusic")
        base = client.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        response = client.session.get(base + "/models", timeout=25, allow_redirects=False,
            headers={"Authorization": "Bearer " + client.api_key})
        if response.status_code != 200:
            print(json.dumps({"status": "failed", "http_status": response.status_code,
                              "song_generated": False}))
            return 1
        models = ModelsResponse.model_validate(response.json())
        selected = next((item for item in models.data if item.id == client.model), None)
        if selected is None or "audio" not in selected.output_modalities:
            raise ValueError("configured model is not an available audio model")
        print(json.dumps({"status": "connected", "provider": client.provider,
            "host": urlparse(client.base_url).hostname, "model": selected.id,
            "reported_pricing": selected.pricing.model_dump() if selected.pricing else None,
            "song_generated": False}, ensure_ascii=True))
        return 0
    except Exception as exc:
        # Do not print exception payloads, raw bodies, headers, or credentials.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "song_generated": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
