"""MCP 工具的中文说明与参数 schema 补全。

FastMCP 从函数签名和 docstring 生成 schema：docstring 常写成英文、参数没有
``description``、``outputSchema`` 只有泛化的 ``object``。这里在 build 之后统一
补一层：
- 工具描述改为「功能 / 参数 / 返回」三段式中文；
- 给常见参数补 description；
- 给泛化的 outputSchema 补一句字段说明。
"""

from __future__ import annotations

from typing import Any

# 工具名 → (一句话功能, 返回说明)
TOOL_DOCS: dict[str, tuple[str, str]] = {
    # ---------- 资产与自选 ----------
    "register_asset": ("登记一个股票/ETF/指数标的（记录交易或拉行情前必须先登记）", "标的档案"),
    "get_asset": ("按代码取单个标的，代码有歧义时同时传 category", "标的档案"),
    "list_assets": ("列出已登记的自选标的，可按分类过滤", "标的数组"),
    "search_assets": ("在本地索引里模糊搜索标的（代码/名称/拼音）", "匹配标的数组"),
    "set_asset_favorite": ("把标的加入或移出自选", "更新后的标的"),
    "refresh_asset_market_data": ("立即排队刷新单只标的的行情", "任务受理结果"),
    "get_market_history": ("读取本地已落库的日线 OHLCV，按日期升序", "K 线数组"),
    "list_tags": ("列出可见的自选分组（系统分组 + 自定义）", "分组数组"),
    "create_tag": ("新建一个空的自选分组", "分组对象"),
    "delete_tag": ("删除自定义分组（系统分类分组不可删）", "删除结果"),
    "pin_tag": ("置顶或取消置顶某个分组", "分组对象"),
    "reorder_tags": ("设置所有分组的完整展示顺序", "分组数组"),
    "add_asset_tag": ("给标的加标签，标签不存在时自动创建", "该标的的标签数组"),
    "remove_asset_tag": ("把标的从某个分组移除", "剩余的标签数组"),
    "update_asset_tags": ("整体替换标的的标签集合", "标签数组"),
    "list_asset_tags": ("查看标的所属分组及加入时的价格快照", "标签数组"),
    "list_tag_assets": ("列出分组内标的的行情摘要", "标的摘要数组"),
    # ---------- 组合与策略 ----------
    "create_portfolio": ("新建组合账本并写入投资画像", "组合详情"),
    "list_portfolios": ("列出全部组合", "组合数组"),
    "get_portfolio": ("取组合的档案、汇总、交易与当前持仓", "组合详情"),
    "update_portfolio": ("修改组合的元数据与投资画像", "组合详情"),
    "get_portfolio_positions": ("按交易流水计算持仓、成本与盈亏", "持仓数组"),
    "get_portfolio_trades": ("列出组合交易流水（倒序）", "交易数组"),
    "add_portfolio_trade": ("往组合账本记一笔买入/卖出/入金/出金", "交易记录"),
    "get_portfolio_opening_snapshot": ("读取组合期初现金与持仓快照", "期初快照"),
    "set_portfolio_opening_snapshot": ("设置组合期初现金与持仓（用于历史收益计算）", "期初快照"),
    "delete_portfolio_opening_snapshot": (
        "删除组合期初快照（之后不能再有交易）",
        "删除结果",
    ),
    "create_strategy": ("兼容别名：等价于 create_portfolio", "组合详情"),
    "list_strategies": ("兼容别名：等价于 list_portfolios", "组合数组"),
    "get_strategy": ("兼容别名：等价于 get_portfolio", "组合详情"),
    "update_strategy": ("兼容别名：等价于 update_portfolio", "组合详情"),
    "get_strategy_positions": ("兼容别名：等价于 get_portfolio_positions", "持仓数组"),
    "get_strategy_trades": ("兼容别名：等价于 get_portfolio_trades", "交易数组"),
    "add_strategy_trade": ("兼容别名：等价于 add_portfolio_trade", "交易记录"),
    "get_strategy_opening_snapshot": ("兼容别名：读取策略期初快照", "期初快照"),
    "set_strategy_opening_snapshot": ("兼容别名：设置策略期初快照", "期初快照"),
    "delete_strategy_opening_snapshot": ("兼容别名：删除策略期初快照", "删除结果"),
    # ---------- 点评与资讯 ----------
    "create_commentary": ("新建一条点评（不可变，修订请用 revise_commentary）", "点评详情"),
    "list_commentaries": ("按对象、日期、来源或全文筛选点评", "点评数组"),
    "get_commentary": ("取单条点评，可要求 Markdown 或结构化块", "点评内容"),
    "revise_commentary": ("在保留原文的前提下创建点评修订版", "点评详情"),
    "list_commentary_information": ("列出点评引用的资讯", "资讯数组"),
    "link_information_to_commentary": ("把一条资讯挂到点评上作为证据", "关联结果"),
    "unlink_information_from_commentary": ("解除点评与资讯的关联", "关联结果"),
    "submit_information": ("提交外部发现的资讯（invest 不会去抓取原文）", "资讯记录"),
    "list_information": ("按对象、时间、来源或文本筛选资讯", "资讯数组"),
    "get_information": ("取单条资讯详情", "资讯详情"),
    # ---------- 交易计划 ----------
    "create_trade_plan": ("创建买卖计划；计划触发也不会自动生成交易", "计划详情"),
    "list_trade_plans": ("按组合、标的、方向、状态或有效期筛选计划", "计划数组"),
    "get_trade_plan": ("取单个计划及其当前状态", "计划详情"),
    "update_trade_plan": ("修改草稿状态的计划", "计划详情"),
    "change_trade_plan_status": ("推进计划生命周期（不会产生交易）", "计划详情"),
    "review_trade_plan": ("记录或替换计划执行后的复盘", "复盘记录"),
    "get_trade_plan_review": ("读取计划的复盘内容", "复盘内容"),
    "get_trade_plan_history": ("列出计划的状态流转历史", "状态事件数组"),
    # ---------- 市场层级 ----------
    "create_market_scope": ("新建市场/行业/主题/商品层级对象", "层级对象"),
    "list_market_scopes": ("按类型或父级列出层级对象", "层级数组"),
    "get_market_scope": ("按 code 取单个层级对象", "层级对象"),
    "update_market_scope": ("修改层级的元数据或父子关系", "层级对象"),
    "delete_market_scope": ("删除空的层级对象", "删除结果"),
    # ---------- 板块与汇率 ----------
    "list_sector_capital_flows": ("按资金流字段给板块排行", "板块资金流数组"),
    "get_sector_capital_flow": ("取单个板块的日频资金流历史", "资金流数组"),
    "get_exchange_rate": ("取指定日或之前的最新 ECB 汇率", "汇率记录"),
    # ---------- 外部能力 ----------
    "wind_data": (
        "Wind 数据工具，按 domain 覆盖股票/基金/指数/债券/宏观/文档/分析",
        "Wind 原始结构化结果",
    ),
    "wind_alice": ("执行 Wind Alice 分析工作流并留档", "分析文本 + run_id"),
    "ifind_news": ("检索 iFinD 财经资讯片段", "资讯条目数组"),
    "ifind_notices": ("检索 iFinD 公告与披露文件", "公告条目数组"),
    "ifind_sector": ("查询 iFinD 板块数据（成分、区间涨跌、净买入）", "Markdown 表格"),
    "yingmi_fund_search": ("按名称或代码检索基金", "基金候选数组"),
    "yingmi_fund_detail": ("基金档案：标签、费率、经理、规模、基准", "基金档案数组"),
    "yingmi_fund_performance": ("基金各周期业绩与风险控制指标", "业绩表"),
    "yingmi_fund_nav": ("基金净值历史", "净值序列"),
    "yingmi_fund_risk": ("基金风险指标：夏普、最大回撤、波动率", "风险指标"),
    "yingmi_fund_diagnosis": ("基金综合诊断：风险/估值/行业/风格/持仓", "诊断报告"),
    "yingmi_fund_news": ("基金相关财经资讯检索", "资讯条目数组"),
    "mx_finance": ("妙想（Choice 库）自然语言查询，domain 决定品种", "结构化查询结果"),
    "indexhub_etf_search": ("全市场 ETF 检索（规模/收益/估值分位/跟踪指数）", "ETF 候选数组"),
    "indexhub_etf_detail": ("ETF 档案：规模、费率、跟踪指数、经理、跟踪误差", "ETF 档案数组"),
    "indexhub_etf_holdings": ("ETF 前十大持仓与权重", "持仓数组"),
    "indexhub_etf_dividends": ("ETF 历史分红记录", "分红数组"),
    "indexhub_etf_by_stock": ("按股票反查持有它的 ETF", "ETF 数组"),
    "indexhub_index_detail": ("指数档案：分类、风险收益、行业与市值分布", "指数档案"),
    "indexhub_index_valuation": ("指数 PE/PB/PS 及 1Y–10Y 历史分位", "估值与分位"),
    "tdx_quote": ("通达信实时快照（单只）", "盘口快照"),
    "tdx_kline": ("通达信 K 线（日/周/月/分钟）", "K 线数组"),
    "tdx_stock_lookup": ("按名称/代码/拼音查标的", "标的候选数组"),
    "tdx_api_data": ("通达信预设数据接口（80+ 种：财务、股东、龙虎榜等）", "预设数据"),
    "tdx_screener": ("通达信自然语言条件选股", "选股结果数组"),
    "tdx_news": ("通达信资讯：news/report/notice/macro", "资讯条目数组"),
    "iwencai_screen": ("问财自然语言选股", "选股结果数组"),
    # ---------- 运维 ----------
    "provider_status": ("查看各外部 provider 的熔断状态与今日调用数", "provider 状态数组"),
    "provider_reset": ("充值或修好 key 后手动解除某个 provider 的熔断", "重置结果"),
    "list_skill_runs": ("列出非结构化 skill 的历史执行记录", "执行记录数组"),
}

# 常见参数说明（按参数名匹配，所有工具共用）。
PARAM_DOCS: dict[str, str] = {
    "refresh": "true = 绕过缓存强制重新拉取（会消耗额度）",
    "output_format": "输出格式：markdown 或 structured",
    "query": "搜索/查询关键词",
    "keyword": "关键词",
    "limit": "返回条数上限",
    "offset": "分页偏移量",
    "page_size": "每页条数",
    "symbol": "标的代码，如 600519.SH",
    "code": "标的代码（6 位）",
    "stock_code": "标的代码，如 600519.SH",
    "asset_symbol": "标的代码，如 600519.SH",
    "category": "标的分类：stock / etf / index",
    "asset_category": "标的分类：stock / etf / index",
    "fund_codes": "基金/ETF 代码数组，如 [\"005827\"]",
    "start_date": "起始日期 YYYY-MM-DD",
    "end_date": "结束日期 YYYY-MM-DD",
    "as_of": "按该日期回看（用于历史时点计算）",
    "trade_date": "交易日 YYYY-MM-DD",
    "order_by": "排序字段",
    "direction": "排序方向：asc / desc",
    "portfolio_id": "组合 ID",
    "strategy_id": "组合 ID（strategy 为兼容别名）",
    "plan_id": "交易计划 ID",
    "commentary_id": "点评 ID",
    "information_id": "资讯 ID",
    "market_scope_code": "市场层级 code",
    "parent_code": "父级层级 code",
    "scope_type": "层级类型：market / sector / theme / commodity",
    "name": "名称",
    "title": "标题",
    "summary": "摘要",
    "description": "描述",
    "content": "正文内容",
    "content_format": "正文格式：markdown 或 structured",
    "source": "来源标识",
    "source_name": "来源名称",
    "source_ref": "来源引用（URL 或外部 ID）",
    "source_commentary_id": "被引用的点评 ID",
    "information_type": "资讯类型",
    "subject_type": "点评对象类型：market / portfolio / asset",
    "tags": "标签名数组",
    "tag": "标签名",
    "action": "动作：buy / sell / deposit / withdraw",
    "status": "状态",
    "reason": "原因/理由",
    "risk_note": "风险提示",
    "amount": "金额",
    "quantity": "数量",
    "currency": "币种，如 CNY / HKD / USD",
    "is_owned": "是否本人账户",
    "investment_style": "投资风格",
    "purpose": "投资目的",
    "investment_direction": "投资方向",
    "position_ratio": "仓位比例",
    "logic": "计划逻辑",
    "conditions": "触发条件数组",
    "valid_from": "有效期开始",
    "valid_until": "有效期结束",
    "confirm_days": "确认天数",
    "session": "会话标识",
    "domain": "数据域：stock/fund/index/bond/econ/docs/analytics（Wind）或 ashare/fund/...（妙想）",
    "arguments": "结构化参数，直接透传给底层工具",
    "kind": "类别：news / report / notice / macro",
    "top_k": "返回条数",
    "message": "自然语言条件描述",
    "entry": "通达信预设数据编号/名称",
    "period": "周期：1d/1w/1m/5m/15m/30m/60m",
    "want_num": "返回 K 线根数",
    "include_full_match": "true = 只返回同时持有全部输入股票的 ETF",
    "page": "页码，从 1 开始",
    "tracked_only": "只返回已同步为 market scope 的板块",
    "sector_code": "东财板块代码，如 BK0428",
    "days": "回看天数",
    "include_hidden": "是否包含未加入自选的隐藏标的",
    "provider_id": "行情源内部代码（可选，通常留空自动推断）",
    "is_favorite": "true = 加入自选，false = 移出",
    "names": "名称数组（用于整体排序）",
    "is_pinned": "true = 置顶",
    "on_date": "指定日期",
    "trading_date": "交易日 YYYY-MM-DD",
    "data_snapshot": "计算盈亏用的数据快照",
    "has_outlook": "点评是否包含展望章节",
    "has_risk": "点评是否包含风险章节",
    "has_trade_plan": "点评是否包含交易计划章节",
    "url": "原文链接",
    "published_at": "发布时间 ISO8601",
    "language": "语言代码，如 zh",
    "search_context": "搜索上下文（记录命中的关键词等）",
    "content_fingerprint": "内容指纹，用于去重",
    "importance": "重要度 1-5",
    "confidence": "置信度 0-1",
    "market_scope_codes": "关联的市场层级 code 数组",
    "assets": "标的引用数组（category + symbol）",
    "published_from": "发布时间下界 YYYY-MM-DD",
    "published_to": "发布时间上界 YYYY-MM-DD",
    "min_importance": "最低重要度",
    "referenced": "是否被点评引用",
    "outcome": "复盘结论",
    "realized_profit": "已实现盈亏",
    "constraints": "投资约束",
    "notes": "备注",
    "snapshot_date": "快照日期",
    "balances": "期初现金余额数组",
    "positions": "期初持仓数组",
    "trade_type": "交易类型",
    "price": "成交价",
    "fee": "手续费",
    "note": "备注",
    "idempotency_key": "幂等键（重复提交不会重复写入）",
    "trade_plan_id": "交易日计划 ID",
    "tool": "底层工具名",
    "question": "自然语言问题（多数外部工具都接收这个参数）",
    "prompt": "分析提示词",
    "skill": "分析技能名称（中文或英文）",
    "time_start": "起始日期 YYYY-MM-DD",
    "time_end": "结束日期 YYYY-MM-DD",
    "size": "返回条数",
    "dimension": "净值区间：oneMonth/quarter/halfYear/oneYear/threeYear/fiveYear",
    "fund_code": "基金代码，如 005827",
    "stock_codes": "股票代码数组",
    "index_codes": "指数代码数组，如 [\"000300\"]",
    "params": "底层工具的附加参数",
    "begin_date": "起始日期 YYYY-MM-DD",
    "provider": "provider 名称：wind/ifind/iwencai/yingmi/mx/indexhub/tdx",
}


def _render(name: str, summary: str, returns: str, params: list[str]) -> str:
    param_line = f"\n\n参数：{'、'.join(params)}" if params else ""
    return f"{summary}。{param_line}\n\n返回：{returns}。"


def enrich_mcp(mcp: Any) -> None:
    """在 build 之后补全工具描述与参数 schema。"""
    for tool in mcp._tool_manager.list_tools():  # noqa: SLF001 - FastMCP 没有公开的遍历接口
        doc = TOOL_DOCS.get(tool.name)
        parameters = tool.parameters or {}
        properties = parameters.get("properties") or {}

        for param_name, prop in properties.items():
            if prop.get("description"):
                continue
            description = PARAM_DOCS.get(param_name)
            if description:
                prop["description"] = description

        if doc and parameters:
            tool.parameters = parameters

        if doc:
            tool.description = _render(
                tool.name, doc[0], doc[1], [p for p in properties if p in PARAM_DOCS]
            )

        # outputSchema 只有泛化 object 时，补一句字段说明。
        output = getattr(tool, "output_schema", None)
        if isinstance(output, dict):
            props = output.get("properties") or {}
            for key, value in props.items():
                if value.get("type") == "object" or value.get("type") == "array":
                    value.setdefault("description", doc[1] if doc else "工具返回")
