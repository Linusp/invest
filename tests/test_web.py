def test_llms_txt_is_public_agent_orientation(client):
    response = client.get("/llms.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# Invest Service" in response.text
    assert "[OpenAPI schema](/openapi.json)" in response.text
    assert "[MCP Streamable HTTP](/mcp/)" in response.text
    assert "category + symbol" in response.text
