# 行情源、搜索索引与定时任务

## 行情源 fallback

`INVEST_MARKET_PROVIDER_ORDER=free_first`（默认）时先使用免费源，取不到或返回空数据后再逐步 fallback。配置问财 API Key 后，问财位于免费源之后、Tushare 之前：

- 个股：AkShare 腾讯 → AkShare 新浪 → 东方财富 → 问财 → Tushare
- 指数：AkShare 腾讯 → AkShare 新浪 → 问财 → Tushare
- ETF：东方财富 → AkShare 新浪 → 问财 → Tushare

`configured_first` 保留 Tushare 主源、AkShare 兜底的旧顺序。`TUSHARE_TOKEN` 未配置时免费源仍可用。`INDEX_FALLBACK_PROVIDER` 和 `ETF_FALLBACK_PROVIDER` 可设为 `none` 关闭对应兜底。

问财使用官方 `https://openapi.iwencai.com/v1/query2data` 和 `hithink-market-query` skill。配置可使用官方名称 `IWENCAI_API_KEY`，也可使用应用名称 `INVEST_IWENCAI_API_KEY`。问财参与历史行情 fallback，并向定时搜索索引提供港股、美股普通股目录；长时间行情范围按自然年分段查询。

成交量统一为股/基金份额，成交额统一为元；Tushare 和东方财富返回的“手/千元”会在写入前换算。问财的股票和 ETF 成交量已是股/份，指数查询未返回成交量时保存为缺失值，不填充为 0。首次同步默认回填十年，后续按 `AUTO_UPDATE_LOOKBACK_DAYS` 回溯，并覆盖最近三天数据。

## 本地搜索索引

搜索只读取数据库中的轻量索引，不请求远端行情源，也不需要 Elasticsearch。索引包含类型、code、名称、别名/曾用名、拼音全拼和首字母，由 RapidFuzz 排序。

Celery Beat 每天在 `SEARCH_INDEX_UPDATE_HOUR`（默认北京时间 3 点）发布构建任务。目录任务合并 AkShare、问财和 Tushare 来源；问财港股代码统一补齐为五位并使用 `.HK`，美股代码统一使用 `.US`，原始代码作为别名保留。单个来源失败不会阻断其他来源。

## 源优先级（PROVIDER_PRIORITY）

`PROVIDER_PRIORITY` 决定历史日线的尝试顺序，从高到低用逗号分隔，默认：

```
akshare,eastmoney,tushare,wind,iwencai
```

- 免费源（AkShare / 东方财富）优先；Tushare 次之；Wind、问财这类按天计次的源排在后面。
- 单个源未配置密钥时自动从链里剔除，不会报错。
- 类别限制保留：指数默认不挂东方财富，ETF 在 `ETF_FALLBACK_PROVIDER=none` 时只走东方财富。
- **iFinD 不参与历史日线**：它的 MCP 只有实时/日内快照（`stock_highfreq_quotes`），没有 K 线工具；
  它只用于 `QUOTE_SNAPSHOT_ENABLED` 的实时快照链。
- Wind 走 `mcp.wind.com.cn/vserver_{stock,index,fund}_data` 的 K 线接口，密钥读
  `WIND_API_KEY_FILE`（Compose 挂载 `~/.dsh/wind.key`）。

## 定时任务

- Beat 默认每 60 分钟发布自选及持仓行情更新任务。
- 每天构建一次标的搜索索引。
- 按 `EXCHANGE_RATE_UPDATE_HOUR`（默认 23 点）发布 ECB 汇率更新任务。
- Worker 执行实际同步任务，部署时保持一个 Beat 实例，Worker 可按负载扩容。

## 关键配置

- `DATABASE_URL`：SQLite、PostgreSQL 或 MySQL SQLAlchemy URL。
- `CELERY_BROKER_URL`：Redis broker URL。
- `AUTO_UPDATE_ENABLED`、`AUTO_UPDATE_INTERVAL_MINUTES`、`AUTO_UPDATE_LOOKBACK_DAYS`：行情更新调度。
- `SEARCH_INDEX_UPDATE_HOUR`：搜索索引更新时间。
- `MARKET_PROVIDER`、`MARKET_PROVIDER_ORDER`、`TUSHARE_TOKEN`、`EASTMONEY_TOKEN`、`IWENCAI_API_KEY`：行情源选择和认证。
- `REPORTING_CURRENCY`、`EXCHANGE_RATE_UPDATE_HOUR`：策略汇总币种和汇率任务。
- `MCP_ALLOWED_HOSTS`、`MCP_ALLOWED_ORIGINS`：MCP 反向代理和浏览器访问控制。

## 板块资金流（东方财富）

`SECTOR_FLOW_ENABLED=true` 时启用。Worker 通过东方财富 push2 接口采集行业板块（BK 板块池，
`m:90+t:2`）的日频资金流（主力/超大单/大单/中单/小单净流入），写入 `sector_capital_flows` 表。
解析逻辑移植自 MIT 许可的 [CapitalPulse](https://github.com/Dr-Liu23/CapitalPulse)。

- 数据范围：行业板块层，不含个股资金流。
- 采集规模：一次全量刷新覆盖全部 BK 板块（约 500 个），逐个请求，耗时约数分钟。
- 调度：`SECTOR_FLOW_UPDATE_HOUR/MINUTE`（默认 15:40）执行收盘后回填；
  `SECTOR_FLOW_UPDATE_MINUTES>0` 时额外按该间隔在盘中刷新当日快照。
- 查询：REST `GET /api/v1/sector-capital-flows`（板块排行）与
  `GET /api/v1/sector-capital-flows/{sector_code}/history`；MCP 工具
  `list_sector_capital_flows`、`get_sector_capital_flow`；`/analysis` 页可查看排行表与主力净流入图。

`SECTOR_FLOW_SYNC_SCOPES_ENABLED=true` 时，按总市值取前 N 个板块（`SECTOR_FLOW_SYNC_SCOPES_TOP`，
默认 30）写入 `market_scopes`，挂到 `SECTOR_FLOW_SYNC_SCOPES_PARENT`（默认 `em_industry`）之下，
使点评可以按板块对象沉淀。该同步**只新建缺失对象，不删除也不覆盖**已有 scope。

### 盘中资金流序列（动画用）

除了日频快照，invest 还按分钟采集板块的**累计净流入**，用于回放开盘到收盘的资金流向变化：

- 数据源：`push2delay.eastmoney.com/api/qt/stock/fflow/kline/get`（`klt=1`），一次请求返回
  当日 240 个时点（09:31–15:00），字段为主力/小/中/大/超大单累计净流入；
- 存储：`sector_flow_points`，按 `(sector_code, ts)` 唯一，每次刷新覆盖写；
- 调度：`SECTOR_FLOW_INTRADAY_MINUTES`（默认 5，0 关闭）在交易时段内运行
  `invest.update_sector_flow_points`，只跟踪市值前 `SECTOR_FLOW_INTRADAY_TOP`（默认 30）个板块；
- 接口：`GET /api/v1/sector-capital-flows/intraday?trade_date=&top=&field=`
  返回对齐好的 `times` 与 `series`；`GET .../intraday/dates` 列出有数据的交易日；
- 页面：`/analysis` 的「盘中资金流动画」用 ECharts 柱状图逐帧回放，可切换交易日、
  指标、板块数与速度；
- 日频收盘结果不受影响，仍写入 `sector_capital_flows`。

东方财富的行业口径是细粒度 BK 板块池（如「银行」「银行Ⅱ」「国有大型银行Ⅲ」并存），
并非官方标准行业分类，引用时注意区分。

## 实时行情快照（iFinD MCP）

`QUOTE_SNAPSHOT_ENABLED=true` 时启用。Worker 通过同花顺 iFinD 官方 MCP 的
`stock_highfreq_quotes` / `index_highfreq_quotes`（`data_mode=real_time`）取盘中快照，
写入 `quote_snapshots`（每个标的覆盖写一行）。

- 采集范围：默认只抓**自选**的 A 股与指数（ETF 不在 iFinD 这两个板块的工具范围内），
  约 52 个标的、6 次 MCP 调用、耗时约 6 秒。
- 调度：`QUOTE_SNAPSHOT_INTERVAL_MINUTES`（默认 30）在 A 股交易时段（09:15–15:10，工作日）
  内执行，非交易时段任务直接返回 `skipped`。
- 估值：`StrategyService.positions()` 在同一天的日线之上优先使用快照价，
  因此盘中组合市值不再停留在昨收。
- 密钥：`IFIND_MCP_KEY_FILE` 指向只读挂载的密钥文件（Compose 挂载
  `~/.dsh/ifind-mcp.key` 到 `/run/secrets/ifind-mcp.key`），也可用 `IFIND_MCP_KEY` 直接给值。
  密钥等同账号权限，不要写进 `.env` 或仓库。
- 额度：iFinD 按工具调用计次（个人基础版 3,000 次/月、免费试用 2,000 次总量）。
  默认配置每交易日约 12 轮 × 6 次 ≈ 72 次调用（约 1,600 次/月）；把间隔调小或关掉「只抓自选」会显著放大消耗。
- 限流：客户端对 429 做 1.5s / 3s 退避重试，并在批次之间留 0.8s 间隔。


配置统一使用 `INVEST_` 前缀，修改 `.env` 后需重启 API、Worker 和 Beat。

## 外部能力（Wind / iFinD / 问财）

这些能力不是「行情源」，而是 invest 本身没有、借外部服务补上的查询与分析入口，
统一通过 MCP 暴露：

| 工具 | 来源 | 说明 | 缓存 |
|---|---|---|---|
| `wind_data` | Wind | 按 `domain` 覆盖 stock/fund/index/bond/econ/docs/analytics 七个域；自然语言或结构化参数都支持 | 6 小时 |
| `wind_alice` | Wind | 14 个分析工作流（公司一页纸、财报点评、可比公司等），返回 Markdown | 24 小时 |
| `list_skill_runs` | 本地 | 列出历史 skill 执行记录（提示词、输出、耗时、是否命中缓存） | — |
| `ifind_news` / `ifind_notices` | iFinD | 新闻与公告片段 | 3 小时 |
| `ifind_sector` | iFinD | 板块数据（成分、区间涨跌、净买入），返回 Markdown | 6 小时 |
| `iwencai_screen` | 问财 | 自然语言选股 | 6 小时 |
| `yingmi_fund_search` / `_detail` / `_performance` / `_nav` / `_risk` / `_diagnosis` | 盈米 | 基金检索、档案、业绩、净值、风险、综合诊断 | 6 小时 |
| `yingmi_fund_news` | 盈米 | 基金相关财经资讯 | 3 小时 |
| `tdx_quote` / `tdx_kline` / `tdx_stock_lookup` / `tdx_api_data` / `tdx_screener` / `tdx_news` | 通达信 | 快照、K 线、标的检索、80+ 预设数据、自然语言选股、资讯/研报/公告/宏观 | 1 分钟–6 小时 |
| `indexhub_etf_search` / `_detail` / `_holdings` / `_dividends` / `_by_stock` | 指数直通车 | 全市场 ETF 检索、档案（费率/规模/跟踪误差）、持仓、分红、按股票反查 ETF | 6 小时 |
| `indexhub_index_detail` / `indexhub_index_valuation` | 指数直通车 | 指数档案与 PE/PB/PS 及 1Y–10Y 分位 | 6 小时 |
| `mx_finance` | 妙想 | 一个入口按 `domain` 覆盖 A股/基金/港股/美股/指数板块/债券/宏观/跨市场/资讯/公告/选股 | 6h（资讯公告 3h） |

实现要点：

- **缓存**：`external_cache` 按 `sha256(source + tool + arguments)` 内容寻址；同参数重复调用不消耗额度。
  设置 `EXTERNAL_CACHE_ENABLED=false` 可关闭，工具参数 `refresh=true` 可单次绕过。
- **运行留档**：非结构化的 `wind_alice` 每次真实执行写一条 `skill_runs`（skill、prompt、输出、
  耗时、是否缓存命中），可用 `list_skill_runs` 回看；缓存命中时也会记录一条 `cache_hit=true`。
- **妙想**：`INVEST_MX_API_KEY` 走 `mxapi.eastmoney.com/mxds/mcp`（请求头 `em_api_key`），
  按积分计费；11 个工具都只收自然语言 `query`，所以收口成一个 `mx_finance(domain, query)`。
- **通达信**：`INVEST_TDX_API_KEY` 走 SkillHub MCP（`testmcp.tdx.com.cn:3001/qclawmcp`），
  普通 `Authorization: Bearer`，需要 `mcp-session-id` 会话；**不是** TdxAiData 后台库那套 key。
  返回体是「一句话摘要 + 内嵌 JSON」的文本块，工具原样透传。
- **指数直通车**：`INVEST_INDEXHUB_API_KEY` 走 `www.etf.com.cn/api/etf-api-service`，
  不是 MCP 而是 REST（`Authorization: Bearer` + `X-Caller-Type: external`）；
  ETF 接口在 `/skill/v1/*`（POST），指数详情/估值在 `/skill/v3/*`（GET）。
  官方额度 500 次/天，可在小程序 AI Skills 页每日再加 500。
- **盈米**：`INVEST_YINGMI_API_KEY` 走 `stargate.yingmi.com/mcp/v2`，服务无状态、静态 `x-api-key`；
  只暴露只读的基金/资讯类工具，不含 `RenderHtmlToPdf` 这类生成类工具。
- **额度**：问财按天计次，耗尽时返回 401 并在错误里写明「当日额度已用完」；Wind Alice 有独立的
  体验期限额，服务端繁忙时会返回「服务繁忙」。
- 结构化结果与 Markdown 原样返回，不做二次改写，避免丢失上游信息。

## Provider 熔断与恢复

所有走 `_metered` 的外部能力（Wind / iFinD / 问财 / 盈米 / 妙想 / 指数直通车）
都受 `provider_state` 状态机保护，不需要手工禁用：

| 触发 | 状态 | 恢复方式 |
|---|---|---|
| 当日调用数达到 `*_DAILY_LIMIT` | `daily` | **次日 00:00 自动恢复** |
| 返回余额/积分不足（「积分余额不足」「额度已用完」「quota exceeded」等） | `credit` | 充值后 `provider_reset`，或每天 09:10 的自动探测成功后恢复 |
| 其它错误（网络、参数） | 不变 | 错误继续往上抛，不熔断 |

- 熔断期间调用**直接报错，不发网络请求、不计数**。
- `provider_status` 查看每个 provider 的状态、原因、今日调用数；
  `provider_reset` 手动解除。
- 自动恢复任务 `invest.recover_provider_states` 每天 09:10 对 `credit` 状态做一次
  轻量 MCP initialize 探测（不消耗业务额度），成功即放行。

## 场外基金

场外基金是与股票/ETF/指数并列的资产类别（`AssetCategory.FUND`），用于构建包含
开放式基金的组合。

- **标的代码**：`{6位代码}.OF`，例如 `005827.OF`；登记时 `category` 传 `fund`。
- **数据源**：AkShare
  - `fund_name_em`：全市场约 2.8 万只基金的目录，进入本地搜索索引，可按名称/代码检索；
  - `fund_open_fund_info_em`：单只基金的单位净值走势，写入 `market_bars`
    （`close` = 单位净值，`change_percent` 直接取「日增长率」，无 OHLC/成交量）。
- **Provider 链**：`akshare-fund → wind(可选)`；AkShare 调用仍走子进程白名单与超时保护。
- **估值**：组合持仓按最新净值估值，`latest_price_date` 即净值日期。
- **限制**：场外基金没有盘中价格、成交量和 K 线形态；图表只画净值曲线。
  申购/赎回费用请记在交易的 `fee` 字段。
