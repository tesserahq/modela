def test_create_domain_service_returns_created(
    client, domain_service_payload, mock_domain_service_nats
):
    response = client.post("/domain-services", json=domain_service_payload)

    assert response.status_code == 201
    payload = response.json()

    assert payload["name"] == domain_service_payload["name"]
    assert payload["domains"] == domain_service_payload["domains"]
    assert payload["base_url"] == domain_service_payload["base_url"]
    assert payload["enabled"] is True
    assert payload["id"]


def test_list_domain_services_returns_enabled_services(
    client, setup_domain_service_factory
):
    enabled_service = setup_domain_service_factory(name="Enabled Service")
    setup_domain_service_factory(name="Disabled Service", enabled=False)

    response = client.get("/domain-services")

    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == str(enabled_service.id)
    assert payload["items"][0]["enabled"] is True


def test_get_domain_service_returns_service(client, setup_domain_service):
    response = client.get(f"/domain-services/{setup_domain_service.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(setup_domain_service.id)
    assert payload["name"] == setup_domain_service.name


def test_update_domain_service_updates_fields(
    client, setup_domain_service, mock_domain_service_nats
):
    payload = {"name": "Updated Service", "enabled": False}

    response = client.put(f"/domain-services/{setup_domain_service.id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(setup_domain_service.id)
    assert data["name"] == "Updated Service"
    assert data["enabled"] is False


def test_delete_domain_service_removes_service(
    client, setup_domain_service, mock_domain_service_nats
):
    response = client.delete(f"/domain-services/{setup_domain_service.id}")

    assert response.status_code == 204

    get_response = client.get(f"/domain-services/{setup_domain_service.id}")
    assert get_response.status_code == 404
