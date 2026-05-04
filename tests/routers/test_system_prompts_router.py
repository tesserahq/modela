"""Router tests for /system-prompts."""

from uuid import uuid4

from fastapi.testclient import TestClient


def test_list_system_prompts_includes_fixture(client: TestClient, setup_system_prompt):
    r = client.get("/system-prompts")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    names = {item["name"] for item in data["items"]}
    assert setup_system_prompt.name in names


def test_get_system_prompt(client: TestClient, setup_system_prompt):
    r = client.get(f"/system-prompts/{setup_system_prompt.name}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == setup_system_prompt.name
    assert body["id"] == str(setup_system_prompt.id)


def test_get_system_prompt_not_found(client: TestClient):
    r = client.get("/system-prompts/nonexistent-prompt-name-xyz")
    assert r.status_code == 404
    assert r.json()["detail"] == "System prompt not found"


def test_get_system_prompt_current(client: TestClient, setup_system_prompt):
    r = client.get(f"/system-prompts/{setup_system_prompt.name}/current")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body
    assert "version_id" in body
    assert body["version_number"] == 1


def test_get_system_prompt_current_not_found(client: TestClient):
    r = client.get("/system-prompts/missing-name/current")
    assert r.status_code == 404


def test_list_system_prompt_versions(
    client: TestClient, setup_system_prompt_with_versions
):
    prompt, versions = setup_system_prompt_with_versions
    r = client.get(f"/system-prompts/{prompt.name}/versions")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    numbers = {item["version_number"] for item in data["items"]}
    assert numbers == {1, 2, 3}
    assert data["items"][0]["version_number"] == 3


def test_list_system_prompt_versions_not_found(client: TestClient):
    r = client.get("/system-prompts/unknown-prompt/versions")
    assert r.status_code == 404


def test_create_system_prompt(client: TestClient):
    name = f"router-create-{uuid4().hex[:10]}"
    r = client.post(
        "/system-prompts",
        json={"name": name, "content": "Hello", "note": "seed"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == name
    assert body["current_version_id"] is not None

    cur = client.get(f"/system-prompts/{name}/current")
    assert cur.status_code == 200
    assert cur.json()["content"] == "Hello"


def test_update_system_prompt_rename(client: TestClient, setup_system_prompt):
    old_name = setup_system_prompt.name
    new_name = f"renamed-{uuid4().hex[:10]}"
    r = client.patch(
        f"/system-prompts/{old_name}",
        json={"name": new_name},
    )
    assert r.status_code == 200
    assert r.json()["name"] == new_name

    missing = client.get(f"/system-prompts/{old_name}")
    assert missing.status_code == 404

    found = client.get(f"/system-prompts/{new_name}")
    assert found.status_code == 200


def test_update_system_prompt_not_found(client: TestClient):
    r = client.patch(
        "/system-prompts/does-not-exist",
        json={"name": "still-missing"},
    )
    assert r.status_code == 404


def test_delete_system_prompt(client: TestClient, setup_system_prompt):
    name = setup_system_prompt.name
    r = client.delete(f"/system-prompts/{name}")
    assert r.status_code == 204

    r2 = client.get(f"/system-prompts/{name}")
    assert r2.status_code == 404


def test_delete_system_prompt_not_found(client: TestClient):
    r = client.delete("/system-prompts/absent-prompt")
    assert r.status_code == 404


def test_create_system_prompt_version(client: TestClient, setup_system_prompt):
    r = client.post(
        f"/system-prompts/{setup_system_prompt.name}/versions",
        json={"content": "Second body", "note": "v2"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["content"] == "Second body"
    assert body["version_number"] == 2

    cur = client.get(f"/system-prompts/{setup_system_prompt.name}/current")
    assert cur.status_code == 200
    assert cur.json()["content"] == "Second body"
    assert cur.json()["version_number"] == 2


def test_create_system_prompt_version_not_found(client: TestClient):
    r = client.post(
        "/system-prompts/ghost/versions",
        json={"content": "x"},
    )
    assert r.status_code == 404
