# dsh-invest

> 本目录是 invest 仓库的一部分，但**与 Python 服务相互隔离**：独立 npm 包、独立测试，
> 不参与镜像构建，只在 DSH 里作为客户端插件加载。

把本地 [invest 服务](../../homelab-infra/invest)（`127.0.0.1:8001`）的数据接进 DeepSeek Harness：
左侧栏一个「投资」入口，面板内五个看板。

## 看板

| 标签 | 内容 | 依赖接口 |
|---|---|---|
| 总览 | 组合总资产/累计盈亏、自选数量、指数涨跌、指数行情卡、组合一览、板块主力净流入 Top5 | `/assets` `/portfolios` `/portfolios/{id}` `/sector-capital-flows` |
| 自选 | 按标签分组筛选、涨跌幅排序、30 日迷你走势、跳转原服务详情 | `/assets` `/tags` `/assets/{symbol}/history` |
| 组合 | 多账户切换、资产/盈亏/仓位、持仓明细与收益、仓位分布条 | `/portfolios` `/portfolios/{id}` |
| 板块资金流 | 按主力/超大/大/中/小单、涨跌幅、市值排序，带横向强弱条 | `/sector-capital-flows` |
| 资金流回放 | 多折线回放开盘到收盘：一条线一个板块，零轴上方流入、下方流出，可播放/暂停/拖进度 | `/sector-capital-flows/intraday` `/sector-capital-flows/intraday/dates` |

## 架构

```
浏览器 (DSH Web, 3080)                 宿主 (dsh web 进程)              invest 服务 (8001)
┌────────────────────────┐   fetch   ┌────────────────────────┐  http  ┌──────────────┐
│ lib/client.js  React   │ ────────▶ │ /dsh-invest/api/v1/*   │ ─────▶ │ FastAPI      │
│ sidebar.panellist + main│  同源     │ lib/proxy.js 反向代理  │        │ /api/v1/*    │
└────────────────────────┘           └────────────────────────┘        └──────────────┘
```

- 浏览器只跟 DSH 自己的 webServer 说话，因此**不需要**改 invest 的 `INVEST_CORS_ORIGINS`。
- 代理只放行 `/api/` 和 `/health`，并把方法、查询串、请求体原样转发；其余路径一律 404。

## 安装（web profile）

按 **profile patch 直接挂载**，不需要重启 web（HMR 会重组配置）：

```bash
# 1. profile 依赖里登记链接包
#    "dsh-invest": "link:/home/zmonster/Projects/homelab-infra/invest/plugin"
cd ~/.dsh/profiles/web && pnpm install

# 2. 在 ~/.dsh/profiles/web/cordis.patch.yml 末尾追加一条 insert
```

```yaml
- insert:
    - id: dsh-invest
      name: 'dsh-invest'
      config:
        baseUrl: 'http://127.0.0.1:8001'
        prefix: '/dsh-invest'
```

不要同时把 `dsh-invest` 写进 `dsh.profile.bundles`：本包自带的 `cordis.patch.yml`
会再 insert 一次同一 id，重启后会出现重复条目。二选一即可。

本包自带的 patch（bundles 方式安装时使用），配置项相同：

```yaml
- insert:
    - id: dsh-invest
      name: 'dsh-invest'
      config:
        baseUrl: 'http://127.0.0.1:8001'
        prefix: '/dsh-invest'
```

## 验证

```bash
# 服务在跑
curl -s http://127.0.0.1:8001/health

# 代理通了（重启 dsh web 之后，带浏览器 cookie 访问）
# 面板里应显示“已连接 127.0.0.1:8001”，否则是红点
```

单元测试（需要 invest 服务在 8001 上运行）：

```bash
node --test test/*.test.mjs
```

## 已知限制

- 板块资金流数据默认不采集。开启方式：`homelab-infra/invest/.env` 加
  `INVEST_SECTOR_FLOW_ENABLED=true` 后 `docker compose up -d` 重建容器。
- 自选看板对每个标的各取一次 30 日历史（带 60 秒缓存），53 个标的约几十个请求；
  后续可换成一个批量接口。
- 只读：不在插件里改自选/持仓/交易，写操作仍回 invest 原服务。
