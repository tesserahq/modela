"""Router tests for /tools."""

from fastapi.testclient import TestClient


def test_list_tools_includes_search_knowledge_base(client: TestClient):
    r = client.get("/tools")
    assert r.status_code == 200
    tools = {item["name"]: item["description"] for item in r.json()}
    assert "search_knowledge_base" in tools
    assert tools["search_knowledge_base"]
