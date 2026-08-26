# REST API 参考

默认前缀为 `/api/v1`。完整请求和响应 schema 以运行中的 OpenAPI 文档 `/docs` 为准。

## 标的与自选

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/assets/search?q=...&category=...` | 从本地索引模糊搜索 |
| `POST` | `/assets` | 手动注册标的 |
| `GET` | `/assets/{category}/{symbol}` | 查询分类明确的标的 |
| `GET` | `/assets/{category}/{symbol}/tags` | 查询分组、加入日期和加入价格 |
| `POST` | `/assets/{category}/{symbol}/tags` | 加入已有或新建分组 |
| `DELETE` | `/assets/{category}/{symbol}/tags/{name}` | 从分组移除标的 |
| `PUT` | `/assets/{category}/{symbol}/tags` | 批量覆盖分组（兼容接口） |
| `PUT` | `/assets/{category}/{symbol}/favorite` | 加入或移出自选 |
| `GET` | `/assets/{category}/{symbol}/history` | 查询历史行情 |
| `POST` | `/assets/{category}/{symbol}/refresh` | 异步触发一次行情抓取 |

## 分组

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/tags` | 查询分组列表 |
| `POST` | `/tags` | 创建空的自定义分组 |
| `DELETE` | `/tags/{name}` | 删除自定义分组；系统分类不可删除 |
| `GET` | `/tags/{name}/assets` | 查询分组内标的 |
| `PUT` | `/tags/{name}/pin` | 设置置顶状态 |
| `PUT` | `/tags/order` | 调整分组顺序 |

## 组合与汇率

组合接口以 `/portfolios` 为入口，包括组合属性 CRUD、期初状态、交易和持仓；原 `/strategies` 路径作为兼容接口保留。组合属性包括初始本金、投资风格、是否自有资产、用途、投资方向、约束和备注。汇率接口为 `GET /exchange-rates/{currency}`。

标的身份由 `category + symbol` 共同确定；不同分类可以使用相同 symbol。交易及期初持仓出现重码时必须传 `asset_category`。证券交易的 `price` 是标的原币种单价，现金流水的 `price` 是现金金额；新增交易可传 `idempotency_key` 安全重试。

首次加入自选会自动进入“个股”“ETF”或“指数”系统分组。每个分组分别保存加入日期和加入价格；从一个分组移除不会影响其他分组，移出自选会清除全部分组关系但保留标的和历史行情。

## 市场对象与点评

`/market-scopes` 提供市场对象的创建、列表、详情、修改和删除接口。`scope_type` 支持 `market`、`sector`、`theme` 和 `commodity`，通过 `parent_code` 组织可扩展层级；有下级或已被点评引用的对象不能删除。

`/commentaries` 提供点评创建、详情和筛选，支持市场对象、组合和标的三类归属，可按交易日期、盘前/盘中/盘后/复盘时段、来源和关键词查询。标的归属必须同时给出 `asset_category + asset_symbol`。点评不可原地修改；`POST /commentaries/{id}/revisions` 会创建保留原文的新修订。

点评正文可用 `structured`、`markdown` 或 `html` 提交。写入后统一保存为 version 1 的结构化 blocks；REST 同时返回安全渲染的 HTML 和 Markdown，MCP 默认返回 Markdown，可用 `output_format=structured` 获取 blocks。

`/information` 用于接收外部工具整理后的资讯，支持多市场对象、多标的关联和无关联资料。相同 URL 幂等更新，不在 Invest 内触发浏览器搜索或抓取。点评通过 `/commentaries/{commentary_id}/information` 查询和维护引用材料。完整工作流见[外部资讯接入](information.md)。

## MCP 工具覆盖

MCP 与上述业务接口保持同一套服务层逻辑，当前提供 53 个工具：

- 标的：`search_assets`、`list_assets`、`get_asset`、`register_asset`、`refresh_asset_market_data`、`get_market_history`、`set_asset_favorite`
- 自选与分组：`list_asset_tags`、`update_asset_tags`、`add_asset_tag`、`remove_asset_tag`、`list_tags`、`create_tag`、`delete_tag`、`reorder_tags`、`pin_tag`、`list_tag_assets`
- 汇率：`get_exchange_rate`
- 组合：`create_portfolio`、`list_portfolios`、`get_portfolio`、`update_portfolio`、`set_portfolio_opening_snapshot`、`get_portfolio_opening_snapshot`、`delete_portfolio_opening_snapshot`、`get_portfolio_trades`、`get_portfolio_positions`、`add_portfolio_trade`
- 组合兼容别名：`create_strategy`、`list_strategies`、`get_strategy`、`update_strategy`、`set_strategy_opening_snapshot`、`get_strategy_opening_snapshot`、`delete_strategy_opening_snapshot`、`get_strategy_trades`、`get_strategy_positions`、`add_strategy_trade`
- 市场对象：`create_market_scope`、`list_market_scopes`、`get_market_scope`、`update_market_scope`、`delete_market_scope`
- 点评：`create_commentary`、`list_commentaries`、`get_commentary`、`revise_commentary`
- 资讯：`submit_information`、`list_information`、`get_information`、`link_information_to_commentary`、`unlink_information_from_commentary`、`list_commentary_information`

MCP 不暴露 Celery 调度、后台同步等运维接口；这些任务由 Beat/Worker 按配置自动执行。
