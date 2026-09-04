from unittest.mock import MagicMock, patch

import pytest

from app.inference.adapters.anthropic import AnthropicProviderAdapter


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    adapter = AnthropicProviderAdapter()
    payload = {
        "data": [
            {"id": "claude-opus-5", "created_at": "2026-07-24T00:00:00Z"},
            {"id": "claude-sonnet-5", "created_at": "2026-06-29T00:00:00Z"},
        ],
        "has_more": False,
        "last_id": "claude-sonnet-5",
    }

    with patch(
        "app.inference.adapters.anthropic.httpx.get", return_value=_response(payload)
    ):
        models = adapter.fetch_live_model_ids()

    assert [m.id for m in models] == ["claude-opus-5", "claude-sonnet-5"]
    assert models[0].created_at.year == 2026


def test_fetch_live_model_ids_follows_pagination(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    adapter = AnthropicProviderAdapter()
    first_page = _response(
        {
            "data": [{"id": "claude-opus-5", "created_at": "2026-07-24T00:00:00Z"}],
            "has_more": True,
            "last_id": "claude-opus-5",
        }
    )
    second_page = _response(
        {
            "data": [{"id": "claude-sonnet-5", "created_at": "2026-06-29T00:00:00Z"}],
            "has_more": False,
            "last_id": "claude-sonnet-5",
        }
    )

    with patch(
        "app.inference.adapters.anthropic.httpx.get",
        side_effect=[first_page, second_page],
    ) as mock_get:
        models = adapter.fetch_live_model_ids()

    assert [m.id for m in models] == ["claude-opus-5", "claude-sonnet-5"]
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1].kwargs["params"] == {"after_id": "claude-opus-5"}


def test_fetch_live_model_ids_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    adapter = AnthropicProviderAdapter()

    with (
        patch(
            "app.inference.adapters.anthropic.httpx.get",
            return_value=_response({}, status_code=500),
        ),
        pytest.raises(Exception),
    ):
        adapter.fetch_live_model_ids()


def test_fetch_live_model_ids_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    adapter = AnthropicProviderAdapter()

    with pytest.raises(ValueError):
        adapter.fetch_live_model_ids()
