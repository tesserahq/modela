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


def _embeddings_response(vectors: list[list[float]]) -> MagicMock:
    response = MagicMock()
    response.data = [MagicMock(embedding=v) for v in vectors]
    return response


def test_create_embeddings_returns_one_vector_per_input_in_order(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    adapter = OpenAIProviderAdapter()
    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]

    with patch("app.inference.adapters.openai.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.embeddings.create.return_value = _embeddings_response(vectors)

        result = adapter.create_embeddings("text-embedding-3-small", ["a", "b", "c"])

    assert result == vectors
    mock_openai_cls.assert_called_once_with(api_key="sk-test")
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small", input=["a", "b", "c"]
    )


def test_create_embeddings_single_item_batch(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    adapter = OpenAIProviderAdapter()

    with patch("app.inference.adapters.openai.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.embeddings.create.return_value = (
            _embeddings_response([[0.9, 0.9]])
        )
        result = adapter.create_embeddings("text-embedding-3-small", ["only one"])

    assert result == [[0.9, 0.9]]


def test_create_embeddings_forwards_api_key_override_without_persisting(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-settings")
    adapter = OpenAIProviderAdapter()

    with patch("app.inference.adapters.openai.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.embeddings.create.return_value = (
            _embeddings_response([[0.1]])
        )
        adapter.create_embeddings(
            "text-embedding-3-small", ["x"], api_key="sk-override"
        )

    mock_openai_cls.assert_called_once_with(api_key="sk-override")


def test_create_embeddings_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = OpenAIProviderAdapter()

    with pytest.raises(ValueError):
        adapter.create_embeddings("text-embedding-3-small", ["x"])


def test_anthropic_create_embeddings_raises_not_implemented():
    from app.inference.adapters.anthropic import AnthropicProviderAdapter

    with pytest.raises(NotImplementedError):
        AnthropicProviderAdapter().create_embeddings("some-model", ["x"])
