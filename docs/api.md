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

组合接口以 `/portfolios` 为入口，包括组合属性 CRUD、期初状态、交易和持仓；原 `/strategies` 路径作为兼容接口保留。组合属性包括初始本金、投资风格、是否自有资产、用途、投资方向、约束和备注。组合页只常驻展示初始本金和计算指标，其他属性从左侧组合列表的 info 入口查看。持仓、交易记录、组合点评和交易计划统一为四个列表 Tab，支持筛选、分页，以及表头“升序 → 降序 → 默认顺序”的三态排序。汇率接口为 `GET /exchange-rates/{currency}`。

标的身份由 `category + symbol` 共同确定；不同分类可以使用相同 symbol。交易及期初持仓出现重码时必须传 `asset_category`。证券交易的 `price` 是标的原币种单价，现金流水的 `price` 是现金金额；新增交易可传 `idempotency_key` 安全重试。

首次加入自选会自动进入“个股”“ETF”或“指数”系统分组。每个分组分别保存加入日期和加入价格；从一个分组移除不会影响其他分组，移出自选会清除全部分组关系但保留标的和历史行情。

## 市场对象与点评

`/market-scopes` 提供市场对象的创建、列表、详情、修改和删除接口。`scope_type` 支持 `market`、`sector`、`theme` 和 `commodity`，通过 `parent_code` 组织可扩展层级；有下级或已被点评引用的对象不能删除。

`/commentaries` 提供点评创建、详情和筛选，支持市场对象、组合和标的三类归属，可按交易日期、盘前/盘中/盘后/复盘时段、来源和关键词查询，并用 `limit + offset` 分页。标的归属必须同时给出 `asset_category + asset_symbol`。点评不可原地修改；`POST /commentaries/{id}/revisions` 会创建保留原文的新修订。页面列表只显示日期、时段、标题、摘要和来源，点击一行后才展示完整正文。

点评正文可用 `structured`、`markdown` 或 `html` 提交。写入后统一保存为 version 1 的结构化 blocks；REST 同时返回安全渲染的 HTML 和 Markdown，MCP 默认返回 Markdown，可用 `output_format=structured` 获取 blocks。

`/information` 用于接收外部工具整理后的资讯，支持多市场对象、多标的关联和无关联资料。相同 URL 幂等更新，不在 Invest 内触发浏览器搜索或抓取。点评通过 `/commentaries/{commentary_id}/information` 查询和维护引用材料。完整工作流见[外部资讯接入](information.md)。

## 交易计划

`/trade-plans` 管理组合内的买卖计划。每条计划明确归属组合和 `category + symbol` 标的，读取结果同时返回 `asset_name`，便于 REST/MCP 客户端一致显示“名称 + 代码”。规模至少填写数量、金额或仓位比例之一；条件支持 `and`/`or`，可配置连续满足交易日数。列表可按组合、标的、动作、状态和有效日期筛选，并用 `limit + offset` 分页。状态通过 `POST /trade-plans/{id}/status` 显式流转，触发只产生待确认状态，不会自动写入交易流水；`GET /trade-plans/{id}/history` 提供不可变状态审计历史。交易流水可通过 `trade_plan_id` 显式关联计划，系统会校验组合和标的一致；计划执行后可通过 `/trade-plans/{id}/review` 保存结构化复盘。

## MCP 工具覆盖

MCP 与上述业务接口保持同一套服务层逻辑，当前提供 61 个工具：

- 标的：`search_assets`、`list_assets`、`get_asset`、`register_asset`、`refresh_asset_market_data`、`get_market_history`、`set_asset_favorite`
- 自选与分组：`list_asset_tags`、`update_asset_tags`、`add_asset_tag`、`remove_asset_tag`、`list_tags`、`create_tag`、`delete_tag`、`reorder_tags`、`pin_tag`、`list_tag_assets`
- 汇率：`get_exchange_rate`
- 组合：`create_portfolio`、`list_portfolios`、`get_portfolio`、`update_portfolio`、`set_portfolio_opening_snapshot`、`get_portfolio_opening_snapshot`、`delete_portfolio_opening_snapshot`、`get_portfolio_trades`、`get_portfolio_positions`、`add_portfolio_trade`
- 组合兼容别名：`create_strategy`、`list_strategies`、`get_strategy`、`update_strategy`、`set_strategy_opening_snapshot`、`get_strategy_opening_snapshot`、`delete_strategy_opening_snapshot`、`get_strategy_trades`、`get_strategy_positions`、`add_strategy_trade`
- 市场对象：`create_market_scope`、`list_market_scopes`、`get_market_scope`、`update_market_scope`、`delete_market_scope`
- 点评：`create_commentary`、`list_commentaries`、`get_commentary`、`revise_commentary`
- 资讯：`submit_information`、`list_information`、`get_information`、`link_information_to_commentary`、`unlink_information_from_commentary`、`list_commentary_information`
- 交易计划：`create_trade_plan`、`list_trade_plans`、`get_trade_plan`、`update_trade_plan`、`change_trade_plan_status`
- 计划复盘：`review_trade_plan`、`get_trade_plan_review`
- 计划审计：`get_trade_plan_history`

MCP 不暴露 Celery 调度、后台同步等运维接口；这些任务由 Beat/Worker 按配置自动执行。

组合工作区在 MCP 中由三个读取工具组合完成：`get_portfolio(portfolio_id)` 返回核心指标、持仓和交易；`list_commentaries(subject_type="portfolio", portfolio_id=...)` 返回点评；`list_trade_plans(portfolio_id=...)` 返回计划。后两个列表都支持 `limit + offset`。`list_trade_plans` 还支持 `action`、`status`、`asset_category + asset_symbol` 和 `as_of`；返回标的名称字段 `asset_name`。

`update_trade_plan` 只允许修改草稿计划，可更新动作、条件、规模、连续确认天数、`valid_from`、`valid_until`、理由、风险和 `source_commentary_id`。未传参数保持原值；计划触发和写入交易仍是两个独立动作。
