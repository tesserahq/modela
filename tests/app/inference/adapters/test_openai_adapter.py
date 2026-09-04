from unittest.mock import MagicMock, patch

import pytest

from app.inference.adapters.openai import OpenAIProviderAdapter


def _response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        response.raise_for_status.return_value = None
    return response


def test_fetch_live_model_ids_maps_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    adapter = OpenAIProviderAdapter()
    payload = {
        "data": [
            {"id": "gpt-4o", "created": 1715000000, "object": "model"},
            {"id": "text-embedding-3-large", "created": 1715000000, "object": "model"},
        ]
    }

    with patch(
        "app.inference.adapters.openai.httpx.get", return_value=_response(payload)
    ):
        models = adapter.fetch_live_model_ids()

    assert [m.id for m in models] == ["gpt-4o", "text-embedding-3-large"]
    assert models[0].created_at.tzinfo is not None


def test_fetch_live_model_ids_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    adapter = OpenAIProviderAdapter()

    with (
        patch(
            "app.inference.adapters.openai.httpx.get",
            return_value=_response({}, status_code=500),
        ),
        pytest.raises(Exception),
    ):
        adapter.fetch_live_model_ids()


def test_fetch_live_model_ids_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = OpenAIProviderAdapter()

    with pytest.raises(ValueError):
        adapter.fetch_live_model_ids()
