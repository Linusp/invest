from datetime import datetime, timedelta, timezone

import pytest

from invest_service.providers.wind_skills import (
    extract_alice_result,
    resolve_alice_skill,
)
from invest_service.services.external_cache import ExternalCacheService, cache_key
from invest_service.services.skill_runs import SkillRunService

ALICE_SSE = (
    'event: message\n'
    'data: {"jsonrpc":"2.0","result":{"kind":"artifact-update",'
    '"artifact":{"name":"agentResult","parts":[{"kind":"data",'
    '"data":{"data":"# 贵州茅台 公司一页纸\\n..."}}]}}}\n\n'
    'event: message\n'
    'data: {"jsonrpc":"2.0","result":{"kind":"artifact-update",'
    '"artifact":{"name":"other","parts":[{"kind":"data",'
    '"data":{"data":"ignored"}}]}}}\n\n'
)


def test_cache_key_is_deterministic_and_argument_order_independent():
    first = cache_key("wind", "get_stock_fundamentals", {"tool": "a", "question": "q"})
    second = cache_key("wind", "get_stock_fundamentals", {"question": "q", "tool": "a"})
    assert first == second
    assert cache_key("wind", "x", {"q": "1"}) != cache_key("wind", "x", {"q": "2"})


def test_cache_roundtrip_and_expiry(session_factory):
    with session_factory() as session:
        cache = ExternalCacheService(session)
        key = cache_key("wind", "t", {"q": "1"})
        cache.put(key, "wind", "t", {"answer": 42}, timedelta(hours=1))
        assert cache.get(key) == {"answer": 42}

    with session_factory() as session:
        cache = ExternalCacheService(session)
        key = cache_key("wind", "t", {"q": "1"})
        row = cache.get(key)
        assert row is not None
        # 人工把过期时间推到过去，再读应当失效并删除。
        from invest_service.models import ExternalCache

        stored = session.get(ExternalCache, key)
        stored.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        session.commit()
        assert cache.get(key) is None


def test_get_or_fetch_only_calls_once_when_cached(session_factory):
    calls = []

    def fetch():
        calls.append(1)
        return {"value": 7}

    with session_factory() as session:
        cache = ExternalCacheService(session)
        first, hit1 = cache.get_or_fetch("wind", "t", {"q": "x"}, timedelta(hours=1), fetch)
        second, hit2 = cache.get_or_fetch("wind", "t", {"q": "x"}, timedelta(hours=1), fetch)

    assert first == second == {"value": 7}
    assert hit1 is False and hit2 is True
    assert len(calls) == 1


def test_skill_runs_are_recorded_and_listed(session_factory):
    with session_factory() as session:
        runs = SkillRunService(session)
        run_id = runs.record(
            source="wind_alice",
            skill="公司一页纸",
            prompt="贵州茅台",
            output="# 分析",
        )
        recent = runs.recent(source="wind_alice")
    assert len(recent) == 1
    assert recent[0].id == run_id
    assert recent[0].prompt == "贵州茅台"


def test_extract_alice_result_reads_agent_result_only():
    assert extract_alice_result(ALICE_SSE).startswith("# 贵州茅台")


def test_extract_alice_result_raises_on_error_event():
    payload = 'event: message\ndata: {"error":{"message":"quota exceeded"}}\n\n'
    with pytest.raises(Exception) as exc:
        extract_alice_result(payload)
    assert "quota" in str(exc.value)


def test_resolve_alice_skill_accepts_chinese_and_english():
    assert resolve_alice_skill("公司一页纸").en == "Company One-Page Investment Memo"
    assert resolve_alice_skill("Company One-Page Investment Memo").zh == "公司一页纸"
    assert resolve_alice_skill(None) is None
    with pytest.raises(Exception):
        resolve_alice_skill("不存在的技能")


def test_ifind_news_items_unwraps_json_string():
    from invest_service.mcp_external import _ifind_news_items

    payload = {"data": {"data": '[{"资讯标题": "标题", "日期": "2026-11-09"}]'}}
    items = _ifind_news_items(payload)
    assert items[0]["资讯标题"] == "标题"
    assert _ifind_news_items({"data": {}}) == []


def test_ifind_markdown_reads_answer_or_string():
    from invest_service.mcp_external import _ifind_markdown

    assert _ifind_markdown({"data": {"answer": "|a|b|"}}) == "|a|b|"
    assert _ifind_markdown({"data": "plain"}) == "plain"
    assert _ifind_markdown({"data": {}}) == ""


def test_extract_alice_result_from_ui_markdown():
    payload = (
        'data: {"jsonrpc":"2.0","result":{"kind":"artifact-update","artifact":{'
        '"parts":[{"kind":"data","data":{"__ui__":{"componentName":"Root","children":['
        '{"componentName":"A2A.Markdown","properties":{"text":["# 结论","正文"]}}]}}}]}}}\n\n'
    )
    assert extract_alice_result(payload) == "# 结论\n正文"


def test_extract_alice_result_raises_on_failed_state():
    payload = (
        'data: {"jsonrpc":"2.0","result":{"kind":"artifact-update","artifact":{'
        '"parts":[{"kind":"data","data":{"__ui__":{"componentName":"Root","children":['
        '{"componentName":"A2A.Markdown","properties":{"text":["抱歉，服务繁忙，请稍后再试"]}}]}}}]}}}\n\n'
        'data: {"jsonrpc":"2.0","result":{"kind":"status-update","status":{"state":"failed"}}}\n\n'
    )
    with pytest.raises(Exception) as exc:
        extract_alice_result(payload)
    assert "服务繁忙" in str(exc.value)


def test_provider_usage_counts_and_limits(session_factory):
    from invest_service.services.provider_usage import ProviderUsageService

    with session_factory() as session:
        usage = ProviderUsageService(session)
        assert usage.count("wind") == 0
        usage.record("wind")
        usage.record("wind", 2)
        assert usage.count("wind") == 3
        usage.ensure_capacity("wind", 10)
        try:
            usage.ensure_capacity("wind", 3)
        except ValueError as exc:
            assert "上限" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("超限应当报错")
        assert usage.recent(days=1)[0]["calls"] == 3


def test_external_rest_endpoints(client):
    response = client.get("/api/v1/external/provider-usage")
    assert response.status_code == 200
    assert response.json() == []

    response = client.get("/api/v1/external/skill-runs")
    assert response.status_code == 200
    assert response.json() == []


def test_wind_domain_whitelist():
    from invest_service.providers.wind_skills import WIND_DOMAIN_TOOLS, WindDataTools

    assert "stock" in WIND_DOMAIN_TOOLS and "bond" in WIND_DOMAIN_TOOLS
    tools = WindDataTools("k")
    with pytest.raises(Exception):
        tools.call("get_bond_basicinfo", "x", "stock")
    with pytest.raises(Exception):
        tools.call("nope", "x", "bond")
    with pytest.raises(Exception):
        tools.call("get_bond_basicinfo", "  ", "bond")
