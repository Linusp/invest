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

## 分组

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/tags` | 查询分组列表 |
| `POST` | `/tags` | 创建空的自定义分组 |
| `DELETE` | `/tags/{name}` | 删除自定义分组；系统分类不可删除 |
| `GET` | `/tags/{name}/assets` | 查询分组内标的 |
| `PUT` | `/tags/{name}/pin` | 设置置顶状态 |
| `PUT` | `/tags/order` | 调整分组顺序 |

## 策略与汇率

策略接口包括策略 CRUD、期初状态、交易和持仓接口；汇率接口为 `GET /exchange-rates/{currency}`。

标的身份由 `category + symbol` 共同确定；不同分类可以使用相同 symbol。交易及期初持仓出现重码时必须传 `asset_category`。证券交易的 `price` 是标的原币种单价，现金流水的 `price` 是现金金额；新增交易可传 `idempotency_key` 安全重试。

首次加入自选会自动进入“个股”“ETF”或“指数”系统分组。每个分组分别保存加入日期和加入价格；从一个分组移除不会影响其他分组，移出自选会清除全部分组关系但保留标的和历史行情。

## MCP 工具覆盖

MCP 与上述业务接口保持同一套服务层逻辑，当前提供 27 个工具：

- 标的：`search_assets`、`list_assets`、`get_asset`、`register_asset`、`get_market_history`、`set_asset_favorite`
- 自选与分组：`list_asset_tags`、`update_asset_tags`、`add_asset_tag`、`remove_asset_tag`、`list_tags`、`create_tag`、`delete_tag`、`reorder_tags`、`pin_tag`、`list_tag_assets`
- 汇率：`get_exchange_rate`
- 策略：`create_strategy`、`list_strategies`、`get_strategy`、`update_strategy`、`set_strategy_opening_snapshot`、`get_strategy_opening_snapshot`、`delete_strategy_opening_snapshot`、`get_strategy_trades`、`get_strategy_positions`、`add_strategy_trade`

MCP 不暴露 Celery 调度、后台同步等运维接口；这些任务由 Beat/Worker 按配置自动执行。
