import asyncio

from invest_service.mcp_server import build_mcp

CN = lambda text: any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))  # noqa: E731


def _tools(session_factory, provider):
    mcp = build_mcp(session_factory, provider)
    return asyncio.run(mcp.list_tools())


def test_every_tool_has_chinese_description_with_returns(session_factory, provider):
    tools = _tools(session_factory, provider)
    assert tools
    for tool in tools:
        assert CN(tool.description), f"{tool.name} 缺少中文描述"
        assert "返回：" in tool.description, f"{tool.name} 缺少返回说明"


def test_every_parameter_has_description(session_factory, provider):
    missing = []
    for tool in _tools(session_factory, provider):
        for name, spec in (tool.inputSchema.get("properties") or {}).items():
            if not spec.get("description"):
                missing.append(f"{tool.name}.{name}")
    assert missing == [], f"缺少参数说明: {missing[:10]}"


def test_tool_docs_cover_all_registered_tools(session_factory, provider):
    from invest_service.mcp_schema import TOOL_DOCS

    names = {tool.name for tool in _tools(session_factory, provider)}
    assert names == set(TOOL_DOCS), {
        "未写文档": sorted(names - set(TOOL_DOCS)),
        "多余文档": sorted(set(TOOL_DOCS) - names),
    }


def _is_structured(schema: dict | None) -> bool:
    schema = schema or {}
    properties = schema.get("properties") or {}
    if schema.get("$defs"):
        return True
    if properties and set(properties) != {"result"}:
        return True
    result = properties.get("result") or {}
    return bool((result.get("items") or {}).get("$ref"))


def test_every_tool_publishes_a_structured_output_schema(session_factory, provider):
    untyped = [
        tool.name
        for tool in _tools(session_factory, provider)
        if not _is_structured(tool.outputSchema)
    ]
    assert untyped == [], f"缺少结构化输出: {untyped}"


def test_known_tools_expose_domain_fields(session_factory, provider):
    tools = {t.name: t for t in _tools(session_factory, provider)}
    assets = tools["search_assets"].outputSchema or {}
    assert "AssetOut" in (assets.get("$defs") or {})

    external = tools["wind_data"].outputSchema or {}
    assert {"data", "cached"} <= set(external.get("properties") or {})

    flows = tools["list_sector_capital_flows"].outputSchema or {}
    assert "SectorFlowRow" in (flows.get("$defs") or {})
