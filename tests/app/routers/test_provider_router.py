def test_list_providers_returns_statuses(client, monkeypatch):
    class DummyProvider:
        name = "algolia"

        def healthcheck(self):
            return True

    def fake_is_provider_enabled(provider_name, settings, settings_manager):
        return provider_name == "algolia"

    def fake_get_providers(settings, settings_manager):
        return [DummyProvider()]

    import app.routers.provider as provider_router

    monkeypatch.setattr(
        provider_router, "is_provider_enabled", fake_is_provider_enabled
    )
    monkeypatch.setattr(provider_router, "get_providers", fake_get_providers)

    response = client.get("/providers")

    assert response.status_code == 200
    payload = response.json()
    items = {item["name"]: item for item in payload["items"]}

    assert items["algolia"]["enabled"] is True
    assert items["algolia"]["healthy"] is True
    assert items["typesense"]["enabled"] is False
    assert items["typesense"]["healthy"] is False
