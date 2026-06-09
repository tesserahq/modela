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
