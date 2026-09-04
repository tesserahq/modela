from unittest.mock import MagicMock, patch


def test_list_providers_includes_parameter_specs(client):
    response = client.get("/providers")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()}

    anthropic = providers["anthropic"]
    assert anthropic["parameters"]["temperature"] == {
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
    }
    assert anthropic["parameters"]["top_p"] == {
        "default": None,
        "min": 0.0,
        "max": 1.0,
    }
    assert anthropic["parameters"]["exclusive_parameter_groups"] == [
        ["temperature", "top_p"]
    ]

    openai = providers["openai"]
    assert openai["parameters"]["temperature"] == {
        "default": 1.0,
        "min": 0.0,
        "max": 2.0,
    }


def test_list_providers_includes_pricing_for_known_models(client):
    response = client.get("/providers")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()}

    openai_models = {m["id"]: m for m in providers["openai"]["models"]}
    gpt_4o = openai_models["gpt-4o"]
    assert float(gpt_4o["input_price_per_mtok"]) > 0
    assert float(gpt_4o["output_price_per_mtok"]) > 0


def test_list_providers_omits_pricing_for_unrecognized_models(client):
    response = client.get("/providers")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()}

    anthropic_models = {m["id"]: m for m in providers["anthropic"]["models"]}
    unreleased_model = anthropic_models["claude-opus-5"]
    assert unreleased_model["input_price_per_mtok"] is None
    assert unreleased_model["output_price_per_mtok"] is None


def test_check_provider_catalog_queues_the_task_and_returns_task_id(client):
    mock_result = MagicMock()
    mock_result.id = "fake-task-id-123"

    with patch(
        "app.routers.providers_router.check_provider_model_catalog_task"
    ) as mock_task:
        mock_task.delay.return_value = mock_result
        response = client.post("/providers/check-catalog")

    assert response.status_code == 202
    assert response.json() == {"task_id": "fake-task-id-123", "status": "queued"}
    mock_task.delay.assert_called_once_with()
