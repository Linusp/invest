# 外部资讯接入

Invest 只负责接收、去重、关联和查询资讯，不负责浏览器搜索或定时抓取。推荐链路是：

```text
OpenCLI / 浏览器搜索 → AI Agent 摘要与显式关联 → Invest MCP / REST → 点评引用
```

## 提交前准备

资讯可以不关联任何对象；需要关联时必须显式提供：

- 市场、行业、主题或商品：先通过 `create_market_scope` 创建稳定代码，再传 `market_scope_codes`；
- 标的：传 `category + symbol`，且标的已存在于本地目录；
- 组合不能作为资讯直接归属，组合点评可以引用资讯。

推荐让 Agent 从搜索结果提取标题、来源、原文 URL、发布时间、摘要、关键事实、查询词、重要性和可信度。正文摘录优先使用 Markdown 或结构化 blocks，不要默认保存整篇受版权保护的原文。

## MCP 工作流

Agent 通过 OpenCLI 获得结果后，调用 `submit_information`：

```json
{
  "title": "银行净息差出现企稳迹象",
  "source_name": "示例财经",
  "url": "https://example.com/news/bank-margin",
  "published_at": "2026-08-26T08:30:00+08:00",
  "summary": "多家银行披露净息差边际改善。",
  "content": "## 关键事实\n- 净息差环比企稳\n- 仍需观察负债成本",
  "content_format": "markdown",
  "information_type": "news",
  "search_context": "银行 净息差",
  "importance": 4,
  "confidence": 0.85,
  "market_scope_codes": ["CN.ASHARE.BANK"],
  "assets": [{"category": "stock", "symbol": "600000.SH"}]
}
```

相同规范化 URL 重复提交会返回同一个资讯 ID，并更新摘要、正文、获取时间和关联对象，不会产生重复记录。也可以显式传 `content_fingerprint` 对同一材料的不同 URL 做上游去重。

常用后续调用：

- `list_information`：按对象、发布时间、来源、类型、关键词、重要性和引用状态筛选；
- `get_information`：读取单条资讯，默认正文为 Markdown；
- `link_information_to_commentary`：把资讯作为某条点评的事实依据；
- `list_commentary_information`：查询点评引用的材料；
- `unlink_information_from_commentary`：移除错误引用，不删除资讯本身。

传 `output_format=structured` 可让 MCP 返回规范 blocks，默认的 `markdown` 更适合 Agent 直接阅读。

## REST 示例

```bash
curl -X POST http://127.0.0.1:8001/api/v1/information \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "宏观流动性观察",
    "source_name": "公开资料",
    "url": "https://example.com/macro/liquidity",
    "published_at": "2026-08-26T07:00:00Z",
    "content": {"version": 1, "blocks": [{"type": "paragraph", "text": "流动性平稳"}]},
    "information_type": "macro"
  }'
```

筛选银行板块的重要新闻：

```bash
curl 'http://127.0.0.1:8001/api/v1/information?market_scope_code=CN.ASHARE.BANK&information_type=news&min_importance=4'
```

页面入口 `/information` 使用同一套 REST 服务，可查看安全渲染后的正文，也可手动提交整理好的资讯。
