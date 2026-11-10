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
