// 浏览器半侧：左侧栏「投资」入口 + 面板内四个看板（总览 / 自选 / 组合 / 板块资金流）。
// 数据全部来自宿主侧同源代理 /dsh-invest/api/v1/*，不直连 invest 服务。
window.__ModuleLoader__.load({
  id: 'dsh-invest',
  factory: (require) => {
    const module = { exports: {} };
    const React = require('react');
    const { jsx: jsxRaw } = require('react/jsx-runtime');
    // jsx-runtime 只认 props.children：把可变子节点收进 props，保持 h(type, props, ...children) 写法
    const h = (type, props, ...children) => {
      const merged = { ...(props || {}) };
      if (children.length === 1) merged.children = children[0];
      else if (children.length > 1) merged.children = children;
      return jsxRaw(type, merged);
    };
    const { useEffect, useMemo, useRef, useState, useCallback } = React;

    const API = '/dsh-invest';
    const PANEL_ID = 'invest';
    const QUOTE_TTL = 60_000;

    /* ------------------------------------------------------------------ 样式 */

    const CSS = `
.iv-root{height:100%;display:flex;flex-direction:column;min-height:0;color:var(--dsw-text-primary,#1f2329);background:var(--dsw-surface-primary,#fff);font-variant-numeric:tabular-nums}
.iv-head{display:flex;align-items:center;gap:12px;padding:14px 20px 0;border-bottom:1px solid var(--dsw-border-subtle,#eceef2);flex-wrap:wrap}
.iv-title{font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px}
.iv-dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:#c9ccd2}
.iv-dot.ok{background:#1a9e5c;box-shadow:0 0 0 3px rgba(26,158,92,.12)}
.iv-dot.bad{background:#d93026;box-shadow:0 0 0 3px rgba(217,48,38,.12)}
.iv-muted{font-size:12px;color:var(--dsw-text-tertiary,#8a9099);font-weight:400}
.iv-spacer{flex:1}
.iv-tabs{display:flex;gap:2px;width:100%;margin-top:10px}
.iv-tab{padding:8px 14px;font-size:13px;color:var(--dsw-text-secondary,#5c6370);cursor:pointer;border:none;background:transparent;border-bottom:2px solid transparent;margin-bottom:-1px}
.iv-tab:hover{color:var(--dsw-text-primary,#1f2329)}
.iv-tab.on{color:var(--dsw-accent,#4d6bfe);border-bottom-color:var(--dsw-accent,#4d6bfe);font-weight:500}
.iv-body{flex:1;overflow:auto;padding:16px 20px 48px}
.iv-btn{height:28px;padding:0 10px;border-radius:7px;border:1px solid var(--dsw-border-default,#dcdfe5);background:transparent;color:inherit;font-size:12px;cursor:pointer}
.iv-btn:hover{background:var(--dsw-surface-secondary,#f2f3f5)}
.iv-btn.on{background:var(--dsw-accent-soft,rgba(77,107,254,.12));border-color:transparent;color:var(--dsw-accent,#4d6bfe)}
.iv-select{height:28px;border-radius:7px;border:1px solid var(--dsw-border-default,#dcdfe5);background:var(--dsw-surface-secondary,#f7f8fa);color:inherit;font-size:12px;padding:0 6px}
.iv-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.iv-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.iv-chip{padding:3px 10px;border-radius:999px;border:1px solid var(--dsw-border-default,#dcdfe5);background:transparent;font-size:12px;cursor:pointer;color:inherit;white-space:nowrap}
.iv-chip:hover{background:var(--dsw-surface-secondary,#f2f3f5)}
.iv-chip.on{background:var(--dsw-accent-soft,rgba(77,107,254,.12));border-color:transparent;color:var(--dsw-accent,#4d6bfe)}
.iv-chips-scroll{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;flex-wrap:nowrap}
.iv-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:16px}
.iv-card{border:1px solid var(--dsw-border-subtle,#eceef2);border-radius:10px;padding:12px 14px;background:var(--dsw-surface-secondary,#fafbfc);min-width:0}
.iv-card h4{margin:0 0 6px;font-size:12px;font-weight:500;color:var(--dsw-text-tertiary,#8a9099)}
.iv-big{font-size:20px;font-weight:600;letter-spacing:-.01em}
.iv-sub{font-size:11px;color:var(--dsw-text-tertiary,#8a9099);margin-top:4px}
.iv-up{color:#d93026}
.iv-down{color:#1a9e5c}
.iv-flat{color:var(--dsw-text-tertiary,#8a9099)}
.iv-sec{margin-bottom:18px}
.iv-sec-h{display:flex;align-items:center;gap:8px;margin:0 0 8px;font-size:13px;font-weight:600}
.iv-table{width:100%;border-collapse:collapse;font-size:12.5px}
.iv-table th{text-align:left;font-weight:500;color:var(--dsw-text-tertiary,#8a9099);font-size:11.5px;padding:6px 8px;border-bottom:1px solid var(--dsw-border-subtle,#eceef2);white-space:nowrap;cursor:pointer;user-select:none}
.iv-table th.num,.iv-table td.num{text-align:right}
.iv-table td{padding:7px 8px;border-bottom:1px solid var(--dsw-border-subtle,#f3f4f6);white-space:nowrap}
.iv-table tbody tr:hover{background:var(--dsw-surface-secondary,#fafbfc)}
.iv-name{display:flex;flex-direction:column;gap:1px;min-width:0}
.iv-name b{font-weight:500;overflow:hidden;text-overflow:ellipsis}
.iv-name span{font-size:11px;color:var(--dsw-text-tertiary,#8a9099)}
.iv-empty{padding:36px 0;text-align:center;color:var(--dsw-text-tertiary,#8a9099);font-size:13px;line-height:1.9}
.iv-empty code{font-size:11.5px;background:var(--dsw-surface-secondary,#f2f3f5);padding:2px 6px;border-radius:5px}
.iv-err{margin:12px 0;padding:10px 12px;border-radius:8px;background:rgba(217,48,38,.08);color:#b3261e;font-size:12px;line-height:1.7;word-break:break-all}
.iv-loading{padding:30px 0;text-align:center;color:var(--dsw-text-tertiary,#8a9099);font-size:12px}
.iv-bar{position:relative;height:6px;border-radius:3px;background:var(--dsw-border-subtle,#eceef2);min-width:60px}
.iv-bar i{position:absolute;top:0;bottom:0;border-radius:3px}
.iv-bar i.pos{left:50%;background:#d93026}
.iv-bar i.neg{right:50%;background:#1a9e5c}
.iv-alloc{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:6px 0 10px}
.iv-alloc i{display:block;height:100%}
.iv-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--dsw-text-tertiary,#8a9099);margin-bottom:14px}
.iv-legend b{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.iv-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 16px;font-size:12.5px;margin-bottom:14px}
.iv-kv span{color:var(--dsw-text-tertiary,#8a9099)}
.iv-link{color:var(--dsw-accent,#4d6bfe);text-decoration:none;font-size:11.5px}
.iv-link:hover{text-decoration:underline}
.iv-scroll-x{overflow-x:auto}
.iv-race{display:flex;flex-direction:column;gap:10px}
.iv-seg{display:inline-flex;gap:2px;background:var(--dsw-surface-secondary,#f3f4f6);border-radius:6px;padding:2px}
.iv-seg-btn{border:0;background:transparent;border-radius:4px;padding:5px 10px;font-size:12px;cursor:pointer;color:var(--dsw-text-secondary,#5c6370)}
.iv-seg-btn.on{background:#fff;color:var(--dsw-text-primary,#1f2329);box-shadow:0 1px 2px rgba(20,30,45,.12)}
.iv-race-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.iv-mini{border:1px solid var(--dsw-border-subtle,#eceef2);border-radius:8px;padding:8px 10px}
.iv-mini-head{display:flex;justify-content:space-between;align-items:baseline;font-size:12px;margin-bottom:2px}
.iv-mini-head strong{font-weight:600}
.iv-mini-legend{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:10.5px;color:var(--dsw-text-tertiary,#8a9099);margin-top:2px}
.iv-mini-legend i{width:8px;height:8px;border-radius:2px;display:inline-block;margin-right:4px}
.iv-pager{display:flex;align-items:center;justify-content:flex-end;gap:8px;font-size:12px}
.iv-race-legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:11.5px;color:var(--dsw-text-secondary,#5c6370)}
.iv-race-legend-item{display:inline-flex;align-items:center;gap:5px;font-variant-numeric:tabular-nums}
.iv-race-legend-item i{width:9px;height:9px;border-radius:2px;display:inline-block}
.iv-race-legend-item b{font-weight:500}
.iv-race-clock{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--dsw-text-tertiary,#8a9099)}
.iv-race-clock b{font-size:14px;color:var(--dsw-text-primary,#1f2329);font-variant-numeric:tabular-nums}
.iv-race-progress{flex:1;min-width:120px}
`;

    function useStyle() {
      useEffect(() => {
        const id = 'dsh-invest/css';
        if (document.getElementById(id)) return;
        const el = document.createElement('style');
        el.id = id;
        el.textContent = CSS;
        document.head.appendChild(el);
      }, []);
    }

    /* ------------------------------------------------------------------ 工具 */

    const num = (v) => {
      if (v === null || v === undefined || v === '') return NaN;
      const n = Number(v);
      return Number.isFinite(n) ? n : NaN;
    };

    const fmt = (v, digits = 2) => {
      const n = num(v);
      if (!Number.isFinite(n)) return '—';
      return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    };

    const money = (v) => {
      const n = num(v);
      if (!Number.isFinite(n)) return '—';
      const abs = Math.abs(n);
      if (abs >= 1e8) return (n / 1e8).toFixed(2) + ' 亿';
      if (abs >= 1e4) return (n / 1e4).toFixed(2) + ' 万';
      return n.toFixed(2);
    };

    const pct = (v) => {
      const n = num(v);
      if (!Number.isFinite(n)) return '—';
      return (n > 0 ? '+' : '') + n.toFixed(2) + '%';
    };

    const signed = (v) => {
      const n = num(v);
      if (!Number.isFinite(n)) return '—';
      return (n > 0 ? '+' : '') + money(n);
    };

    const toneOf = (v) => {
      const n = num(v);
      if (!Number.isFinite(n) || n === 0) return 'iv-flat';
      return n > 0 ? 'iv-up' : 'iv-down';
    };

    const arrow = (v) => {
      const n = num(v);
      if (!Number.isFinite(n) || n === 0) return '';
      return n > 0 ? '▲' : '▼';
    };

    const today = () => new Date().toLocaleDateString('zh-CN');
    const openInInvest = (symbol, category) =>
      `http://127.0.0.1:8001/asset/${category}/${symbol}`;

    /* ------------------------------------------------------------------ 取数 */

    async function getJson(path, signal) {
      const res = await fetch(`${API}${path}`, { signal, cache: 'no-store' });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail || body?.error || `HTTP ${res.status}`);
      return body;
    }

    function useJson(path, tick) {
      const [state, setState] = useState({ data: null, error: null, loading: true });

      useEffect(() => {
        if (!path) return undefined;
        let alive = true;
        const ac = new AbortController();
        setState((s) => ({ ...s, loading: true, error: null }));
        getJson(path, ac.signal)
          .then((data) => {
            if (alive) setState({ data, error: null, loading: false });
          })
          .catch((error) => {
            if (alive && error.name !== 'AbortError') {
              setState({ data: null, error: String(error.message || error), loading: false });
            }
          });
        return () => {
          alive = false;
          ac.abort();
        };
      }, [path, tick]);

      return state;
    }

    const quoteCache = new Map();

    // symbols -> { [symbol]: { close, changePercent, bars } }
    function useQuotes(symbols, tick, limit = 30) {
      const [map, setMap] = useState({});
      const key = symbols.join(',');

      useEffect(() => {
        if (!symbols.length) return undefined;
        let alive = true;
        const ac = new AbortController();

        const cached = {};
        const todo = [];
        for (const symbol of symbols) {
          const hit = quoteCache.get(symbol);
          if (hit && Date.now() - hit.t < QUOTE_TTL && hit.limit >= limit) cached[symbol] = hit.value;
          else todo.push(symbol);
        }
        if (Object.keys(cached).length) setMap(cached);

        let cursor = 0;
        const worker = async () => {
          while (alive && cursor < todo.length) {
            const symbol = todo[cursor++];
            try {
              const bars = await getJson(
                `/api/v1/assets/${encodeURIComponent(symbol)}/history?limit=${limit}`,
                ac.signal,
              );
              if (!alive) return;
              const last = bars[bars.length - 1];
              const value = {
                close: num(last?.close),
                changePercent: num(last?.change_percent),
                bars: bars.map((b) => num(b.close)).filter((n) => Number.isFinite(n)),
              };
              quoteCache.set(symbol, { t: Date.now(), limit, value });
              setMap((prev) => ({ ...prev, [symbol]: value }));
            } catch (error) {
              if (error.name === 'AbortError') return;
            }
          }
        };
        Promise.all([worker(), worker(), worker(), worker(), worker(), worker()]);

        return () => {
          alive = false;
          ac.abort();
        };
      }, [key, tick, limit]);

      return map;
    }

    function usePortfolioSummaries(portfolios, tick) {
      const [rows, setRows] = useState([]);
      const ids = portfolios.map((p) => p.id).join(',');

      useEffect(() => {
        if (!portfolios.length) return undefined;
        let alive = true;
        setRows([]);
        Promise.all(
          portfolios.map((p) =>
            getJson(`/api/v1/portfolios/${p.id}`)
              .then((detail) => ({ ...p, summary: detail.summary, positions: detail.positions || [] }))
              .catch(() => ({ ...p, summary: null, positions: [] })),
          ),
        ).then((list) => {
          if (alive) setRows(list);
        });
        return () => {
          alive = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [ids, tick]);

      return rows;
    }

    /* ------------------------------------------------------------------ 通用组件 */

    function Stat({ label, value, tone, sub }) {
      return h(
        'div',
        { className: 'iv-card' },
        h('h4', {}, label),
        h('div', { className: 'iv-big ' + (tone || '') }, value),
        sub ? h('div', { className: 'iv-sub' }, sub) : null,
      );
    }

    function Loading({ text }) {
      return h('div', { className: 'iv-loading' }, text || '加载中…');
    }

    function ErrorBox({ error, onRetry }) {
      return h(
        'div',
        { className: 'iv-err' },
        h('div', {}, '请求失败：' + error),
        h(
          'div',
          { style: { marginTop: 6 } },
          h('button', { className: 'iv-btn', onClick: onRetry }, '重试'),
        ),
      );
    }

    function Sparkline({ values, width = 96, height = 26 }) {
      if (!values || values.length < 2) return h('span', { className: 'iv-muted' }, '—');
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const step = width / (values.length - 1);
      const points = values.map((v, i) => {
        const x = i * step;
        const y = height - ((v - min) / span) * (height - 2) - 1;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      const up = values[values.length - 1] >= values[0];
      const color = up ? '#d93026' : '#1a9e5c';
      return h(
        'svg',
        { width, height, viewBox: `0 0 ${width} ${height}`, 'aria-hidden': 'true' },
        h('polyline', {
          points,
          fill: 'none',
          stroke: color,
          strokeWidth: 1.4,
          strokeLinejoin: 'round',
          strokeLinecap: 'round',
        }),
      );
    }

    function FlowBar({ value, max }) {
      const v = num(value);
      const m = Math.max(num(max) || 0, 1);
      const ratio = Math.min(Math.abs(v) / m, 1) * 50;
      if (!Number.isFinite(v) || v === 0) return h('div', { className: 'iv-bar' });
      return h(
        'div',
        { className: 'iv-bar' },
        h('i', { className: v > 0 ? 'pos' : 'neg', style: { width: ratio + '%' } }),
      );
    }

    function Empty({ children }) {
      return h('div', { className: 'iv-empty' }, children);
    }

    /* ------------------------------------------------------------------ 总览 */

    function Overview({ tick, go }) {
      const assets = useJson('/api/v1/assets', tick);
      const portfolios = useJson('/api/v1/portfolios', tick);
      const flows = useJson('/api/v1/sector-capital-flows?limit=5&order_by=main_net&direction=desc', tick);

      const list = Array.isArray(assets.data) ? assets.data : [];
      const indices = useMemo(() => list.filter((a) => a.category === 'index'), [assets.data]);
      const quotes = useQuotes(indices.map((a) => a.symbol), tick, 2);
      const pfList = Array.isArray(portfolios.data) ? portfolios.data : [];
      const pfRows = usePortfolioSummaries(pfList, tick);

      const totals = useMemo(() => {
        let value = 0;
        let profit = 0;
        let contribution = 0;
        let cash = 0;
        for (const p of pfRows) {
          if (!p.summary) continue;
          value += num(p.summary.total_value) || 0;
          profit += num(p.summary.total_profit) || 0;
          contribution += num(p.summary.net_contribution) || 0;
          cash += num(p.summary.cash_balance) || 0;
        }
        return { value, profit, contribution, cash, rate: contribution ? (profit / contribution) * 100 : NaN };
      }, [pfRows]);

      const indexMoves = indices.map((a) => quotes[a.symbol]).filter(Boolean);
      const upCount = indexMoves.filter((q) => q.changePercent > 0).length;
      const downCount = indexMoves.filter((q) => q.changePercent < 0).length;
      const byCategory = list.reduce((acc, a) => {
        acc[a.category] = (acc[a.category] || 0) + 1;
        return acc;
      }, {});
      const flowRows = flows.data?.rows || [];

      const loading = assets.loading && !list.length;

      return h(
        'div',
        {},
        loading
          ? h(Loading)
          : h(
              'div',
              { className: 'iv-cards' },
              h(Stat, {
                label: '组合总资产',
                value: money(totals.value),
                sub: `现金 ${money(totals.cash)}`,
              }),
              h(Stat, {
                label: '累计盈亏',
                value: signed(totals.profit),
                tone: toneOf(totals.profit),
                sub: Number.isFinite(totals.rate) ? `收益率 ${pct(totals.rate)}` : '无投入基准',
              }),
              h(Stat, {
                label: '自选标的',
                value: String(list.length),
                sub: `${byCategory.stock || 0} 个股 · ${byCategory.index || 0} 指数 · ${byCategory.etf || 0} ETF`,
              }),
              h(Stat, {
                label: '指数今日',
                value: `${upCount} 涨 / ${downCount} 跌`,
                sub: today(),
              }),
            ),

        h(
          'div',
          { className: 'iv-sec' },
          h('div', { className: 'iv-sec-h' }, '指数行情'),
          assets.error
            ? h(ErrorBox, { error: assets.error, onRetry: () => go('refresh') })
            : h(
                'div',
                { className: 'iv-cards' },
                indices.map((a) => {
                  const q = quotes[a.symbol];
                  return h(
                    'div',
                    { className: 'iv-card', key: a.symbol },
                    h('h4', {}, a.name),
                    h(
                      'div',
                      { className: 'iv-big ' + toneOf(q?.changePercent) },
                      q ? fmt(q.close) : '—',
                    ),
                    h(
                      'div',
                      { className: 'iv-sub ' + toneOf(q?.changePercent) },
                      q ? `${arrow(q.changePercent)} ${pct(q.changePercent)}` : '取数中…',
                    ),
                  );
                }),
                !indices.length && !assets.loading ? h(Empty, {}, '还没有指数类自选标的') : null,
              ),
        ),

        h(
          'div',
          { className: 'iv-sec' },
          h('div', { className: 'iv-sec-h' }, '组合一览'),
          pfRows.length
            ? h(
                'div',
                { className: 'iv-scroll-x' },
                h(
                  'table',
                  { className: 'iv-table' },
                  h('thead', {}, h('tr', {},
                    h('th', {}, '组合'),
                    h('th', { className: 'num' }, '总资产'),
                    h('th', { className: 'num' }, '持仓市值'),
                    h('th', { className: 'num' }, '总盈亏'),
                    h('th', { className: 'num' }, '仓位'),
                  )),
                  h('tbody', {}, pfRows.map((p) => {
                    const s = p.summary;
                    const mv = num(s?.market_value) || 0;
                    const tv = num(s?.total_value) || 0;
                    return h('tr', { key: p.id },
                      h('td', {}, h('div', { className: 'iv-name' }, h('b', {}, p.name), h('span', {}, s ? `现金 ${money(s.cash_balance)}` : '无数据'))),
                      h('td', { className: 'num' }, money(tv)),
                      h('td', { className: 'num' }, money(mv)),
                      h('td', { className: 'num ' + toneOf(s?.total_profit) }, signed(s?.total_profit)),
                      h('td', { className: 'num' }, tv ? `${((mv / tv) * 100).toFixed(1)}%` : '—'),
                    );
                  })),
                ),
              )
            : portfolios.loading
              ? h(Loading, { text: '加载组合…' })
              : h(Empty, {}, '还没有组合'),
        ),

        h(
          'div',
          { className: 'iv-sec' },
          h('div', { className: 'iv-sec-h' }, '板块主力净流入 Top5'),
          flowRows.length
            ? h(
                'table',
                { className: 'iv-table' },
                h('tbody', {}, flowRows.map((r) => h('tr', { key: r.sector_code },
                  h('td', {}, r.sector_name),
                  h('td', { className: 'num ' + toneOf(r.main_net) }, signed(r.main_net)),
                  h('td', { className: 'num ' + toneOf(r.change_percent) }, pct(r.change_percent)),
                ))),
              )
            : h(Empty, {}, '暂无板块资金流数据 — 采集默认关闭，在 invest 的 .env 里设置 ',
                h('code', {}, 'INVEST_SECTOR_FLOW_ENABLED=true'), ' 后重启容器即可。'),
        ),
      );
    }

    /* ------------------------------------------------------------------ 自选行情 */

    function Watchlist({ tick }) {
      const assets = useJson('/api/v1/assets', tick);
      const tags = useJson('/api/v1/tags', tick);
      const [tag, setTag] = useState('全部');
      const [sort, setSort] = useState('change');

      const list = useMemo(() => {
        const all = Array.isArray(assets.data) ? assets.data : [];
        return all.filter((a) => a.is_favorite && (tag === '全部' || (a.tags || []).some((t) => t.name === tag)));
      }, [assets.data, tag]);

      const quotes = useQuotes(list.map((a) => a.symbol), tick, 30);

      const rows = useMemo(() => {
        const copy = list.slice();
        if (sort === 'change') {
          copy.sort((a, b) => (num(quotes[b.symbol]?.changePercent) || -1e9) - (num(quotes[a.symbol]?.changePercent) || -1e9));
        } else if (sort === 'name') {
          copy.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));
        }
        return copy;
      }, [list, sort, quotes]);

      const tagList = useMemo(() => {
        const arr = Array.isArray(tags.data) ? tags.data.slice() : [];
        arr.sort((a, b) => (a.position ?? 99) - (b.position ?? 99));
        return ['全部', ...arr.map((t) => t.name)];
      }, [tags.data]);

      if (assets.loading && !list.length) return h(Loading);

      return h(
        'div',
        {},
        h(
          'div',
          { className: 'iv-chips iv-chips-scroll' },
          tagList.map((t) => h(
            'button',
            { key: t, className: 'iv-chip' + (tag === t ? ' on' : ''), onClick: () => setTag(t) },
            t,
          )),
        ),

        h(
          'div',
          { className: 'iv-row', style: { marginBottom: 10 } },
          h('span', { className: 'iv-muted' }, `${rows.length} 个标的`),
          h('div', { className: 'iv-spacer' }),
          h('span', { className: 'iv-muted' }, '排序'),
          h('button', { className: 'iv-btn' + (sort === 'change' ? ' on' : ''), onClick: () => setSort('change') }, '涨跌幅'),
          h('button', { className: 'iv-btn' + (sort === 'name' ? ' on' : ''), onClick: () => setSort('name') }, '名称'),
        ),

        assets.error
          ? h(ErrorBox, { error: assets.error, onRetry: () => window.location.reload() })
          : h(
              'div',
              { className: 'iv-scroll-x' },
              h(
                'table',
                { className: 'iv-table' },
                h('thead', {}, h('tr', {},
                  h('th', {}, '标的'),
                  h('th', { className: 'num' }, '最新价'),
                  h('th', { className: 'num' }, '涨跌幅'),
                  h('th', {}, '30 日走势'),
                  h('th', {}, '标签'),
                  h('th', {}, ''),
                )),
                h('tbody', {}, rows.map((a) => {
                  const q = quotes[a.symbol];
                  return h('tr', { key: a.symbol },
                    h('td', {}, h('div', { className: 'iv-name' },
                      h('b', {}, a.name),
                      h('span', {}, `${a.symbol} · ${a.category}`),
                    )),
                    h('td', { className: 'num' }, q ? fmt(q.close, a.category === 'etf' ? 3 : 2) : '—'),
                    h('td', { className: 'num ' + toneOf(q?.changePercent) },
                      q ? `${arrow(q.changePercent)} ${pct(q.changePercent)}` : '—'),
                    h('td', {}, h(Sparkline, { values: q?.bars })),
                    h('td', {}, (a.tags || []).map((t) => h('span', { key: t.name, className: 'iv-muted', style: { marginRight: 6 } }, t.name))),
                    h('td', {}, h('a', { className: 'iv-link', href: openInInvest(a.symbol, a.category), target: '_blank', rel: 'noreferrer' }, '打开')),
                  );
                })),
              ),
            ),
        !rows.length && !assets.loading ? h(Empty, {}, '这个标签下没有自选标的') : null,
      );
    }

    /* ------------------------------------------------------------------ 组合持仓 */

    function Portfolios({ tick }) {
      const portfolios = useJson('/api/v1/portfolios', tick);
      const [selected, setSelected] = useState(null);
      const list = Array.isArray(portfolios.data) ? portfolios.data : [];

      useEffect(() => {
        if (!selected && list.length) setSelected(list[0].id);
      }, [list.length, selected]);

      const detail = useJson(selected ? `/api/v1/portfolios/${selected}` : null, tick);

      if (portfolios.loading && !list.length) return h(Loading);
      if (!list.length) return h(Empty, {}, '还没有组合');

      const d = detail.data;
      const s = d?.summary;
      const positions = d?.positions || [];

      const totalMv = positions.reduce((sum, p) => sum + (num(p.market_value) || 0), 0);
      const cash = num(s?.cash_balance) || 0;
      const base = totalMv + cash || 1;
      const palette = ['#4d6bfe', '#d93026', '#f5a623', '#1a9e5c', '#8b5cf6', '#0ea5e9', '#ec4899', '#84cc16'];

      return h(
        'div',
        {},
        h(
          'div',
          { className: 'iv-chips iv-chips-scroll' },
          list.map((p) => h(
            'button',
            { key: p.id, className: 'iv-chip' + (selected === p.id ? ' on' : ''), onClick: () => setSelected(p.id) },
            p.name,
          )),
        ),

        detail.error
          ? h(ErrorBox, { error: detail.error, onRetry: () => window.location.reload() })
          : detail.loading && !d
            ? h(Loading, { text: '加载组合…' })
            : h(
                'div',
                {},
                h(
                  'div',
                  { className: 'iv-cards' },
                  h(Stat, { label: '总资产', value: money(s?.total_value), sub: `持仓 ${money(s?.market_value)} · 现金 ${money(cash)}` }),
                  h(Stat, { label: '总盈亏', value: signed(s?.total_profit), tone: toneOf(s?.total_profit), sub: `已实现 ${signed(s?.realized_profit)} · 浮盈 ${signed(s?.unrealized_profit)}` }),
                  h(Stat, { label: '净投入', value: money(s?.net_contribution), sub: num(s?.net_contribution) ? `收益率 ${pct((num(s?.total_profit) / num(s?.net_contribution)) * 100)}` : '—' }),
                  h(Stat, { label: '持仓数', value: String(positions.length), sub: num(s?.win_rate) >= 0 ? `胜率 ${(num(s.win_rate) * 100).toFixed(0)}%` : '—' }),
                ),

                h('div', { className: 'iv-alloc' },
                  positions.map((p, i) => h('i', {
                    key: p.asset?.symbol ?? i,
                    style: { width: ((num(p.market_value) || 0) / base) * 100 + '%', background: palette[i % palette.length] },
                    title: p.asset?.name,
                  })),
                  h('i', { style: { width: (cash / base) * 100 + '%', background: '#d5d8de' }, title: '现金' }),
                ),
                h('div', { className: 'iv-legend' },
                  positions.slice(0, 8).map((p, i) => h('span', { key: p.asset?.symbol ?? i },
                    h('b', { style: { background: palette[i % palette.length] } }), p.asset?.name)),
                  h('span', {}, h('b', { style: { background: '#d5d8de' } }), '现金'),
                ),

                positions.length
                  ? h('div', { className: 'iv-scroll-x' },
                      h('table', { className: 'iv-table' },
                        h('thead', {}, h('tr', {},
                          h('th', {}, '标的'),
                          h('th', { className: 'num' }, '数量'),
                          h('th', { className: 'num' }, '成本'),
                          h('th', { className: 'num' }, '现价'),
                          h('th', { className: 'num' }, '市值'),
                          h('th', { className: 'num' }, '浮动盈亏'),
                          h('th', { className: 'num' }, '占比'),
                        )),
                        h('tbody', {}, positions.map((p, i) => {
                          const pctOfBook = totalMv ? ((num(p.market_value) || 0) / base) * 100 : 0;
                          const cost = num(p.average_cost);
                          const last = num(p.latest_price);
                          const ret = cost && Number.isFinite(last) ? ((last / cost - 1) * 100) : NaN;
                          return h('tr', { key: p.asset?.symbol ?? i },
                            h('td', {}, h('div', { className: 'iv-name' },
                              h('b', {}, p.asset?.name ?? '—'),
                              h('span', {}, `${p.asset?.symbol ?? ''} · 现价日 ${p.latest_price_date ?? '—'}`))),
                            h('td', { className: 'num' }, fmt(p.quantity, 0)),
                            h('td', { className: 'num' }, fmt(cost, 3)),
                            h('td', { className: 'num' }, fmt(last, 3)),
                            h('td', { className: 'num' }, money(p.market_value)),
                            h('td', { className: 'num ' + toneOf(p.unrealized_profit) },
                              signed(p.unrealized_profit) + (Number.isFinite(ret) ? ` (${pct(ret)})` : '')),
                            h('td', { className: 'num' }, pctOfBook.toFixed(1) + '%'),
                          );
                        })),
                      ),
                    )
                  : h(Empty, {}, '这个组合还没有持仓'),
              ),
      );
    }

    /* ------------------------------------------------------------------ 板块资金流 */

    const FLOW_FIELDS = [
      ['main_net', '主力净流入'],
      ['super_large_net', '超大单'],
      ['large_net', '大单'],
      ['mid_net', '中单'],
      ['small_net', '小单'],
      ['change_percent', '涨跌幅'],
      ['market_cap', '市值'],
    ];

    function SectorFlows({ tick }) {
      const [orderBy, setOrderBy] = useState('main_net');
      const [direction, setDirection] = useState('desc');
      const res = useJson(`/api/v1/sector-capital-flows?limit=40&order_by=${orderBy}&direction=${direction}`, tick);

      const rows = res.data?.rows || [];
      const isAmount = orderBy !== 'change_percent';
      const max = rows.reduce((m, r) => Math.max(m, Math.abs(num(r[orderBy]) || 0)), 0);

      return h(
        'div',
        {},
        h(
          'div',
          { className: 'iv-row', style: { marginBottom: 12 } },
          h('span', { className: 'iv-muted' }, '排序'),
          h('select', { className: 'iv-select', value: orderBy, onChange: (e) => setOrderBy(e.target.value) },
            FLOW_FIELDS.map(([field, label]) => h('option', { key: field, value: field }, label))),
          h('button', { className: 'iv-btn' + (direction === 'desc' ? ' on' : ''), onClick: () => setDirection('desc') }, '从高到低'),
          h('button', { className: 'iv-btn' + (direction === 'asc' ? ' on' : ''), onClick: () => setDirection('asc') }, '从低到高'),
          h('div', { className: 'iv-spacer' }),
          res.data?.trade_date ? h('span', { className: 'iv-muted' }, '交易日 ' + res.data.trade_date) : null,
        ),

        res.error
          ? h(ErrorBox, { error: res.error, onRetry: () => window.location.reload() })
          : res.loading && !rows.length
            ? h(Loading)
            : rows.length
              ? h('div', { className: 'iv-scroll-x' },
                  h('table', { className: 'iv-table' },
                    h('thead', {}, h('tr', {},
                      h('th', {}, '#'),
                      h('th', {}, '板块'),
                      h('th', { className: 'num' }, FLOW_FIELDS.find(([f]) => f === orderBy)?.[1] ?? ''),
                      h('th', {}, '强弱'),
                      h('th', { className: 'num' }, '涨跌幅'),
                      h('th', { className: 'num' }, '市值'),
                    )),
                    h('tbody', {}, rows.map((r, i) => {
                      const v = r[orderBy];
                      return h('tr', { key: r.sector_code ?? i },
                        h('td', { className: 'iv-muted' }, String(i + 1)),
                        h('td', {}, h('div', { className: 'iv-name' }, h('b', {}, r.sector_name), h('span', {}, r.sector_code))),
                        h('td', { className: 'num ' + toneOf(v) }, isAmount ? signed(v) : pct(v)),
                        h('td', {}, h(FlowBar, { value: isAmount ? v : r.main_net, max })),
                        h('td', { className: 'num ' + toneOf(r.change_percent) }, pct(r.change_percent)),
                        h('td', { className: 'num' }, money(r.market_cap)),
                      );
                    })),
                  ),
                )
              : h(Empty, {},
                  h('div', {}, '暂无板块资金流数据'),
                  h('div', {}, '采集默认关闭。在 ', h('code', {}, '~/Projects/homelab-infra/invest/.env'), ' 里加一行 ',
                    h('code', {}, 'INVEST_SECTOR_FLOW_ENABLED=true'), '，然后 ',
                    h('code', {}, 'docker compose up -d'), ' 重建容器；'),
                  h('div', {}, '开启后 beat 会在每个交易日 15:40 做一次 EOD 回填。'),
                ),
      );
    }

    /* ------------------------------------------------------------------ 资金流回放 */

    const RACE_FIELDS = [
      ['main_net', '主力净流入'],
      ['super_large_net', '超大单'],
      ['large_net', '大单'],
      ['mid_net', '中单'],
      ['small_net', '小单'],
    ];

    function yi(value) {
      const n = Number(value);
      if (!Number.isFinite(n)) return '—';
      return (n / 1e8).toFixed(1) + '亿';
    }

    const RACE_PALETTE = [
      '#4d6bfe', '#d93026', '#f5a623', '#1a9e5c', '#8b5cf6', '#0ea5e9',
      '#ec4899', '#84cc16', '#f97316', '#14b8a6', '#a855f7', '#eab308',
      '#06b6d4', '#ef4444', '#22c55e', '#6366f1', '#f43f5e', '#10b981',
      '#a16207', '#7c3aed',
    ];

    const RACE_LOG_BASE = 1e8; // 对数刻度的基准：1 亿

    function raceTransform(value, mode) {
      if (mode !== 'log') return value;
      return Math.sign(value) * Math.log10(1 + Math.abs(value) / RACE_LOG_BASE);
    }

    function raceTicks(maxAbs, mode) {
      if (mode !== 'log') return [maxAbs, maxAbs / 2, 0, -maxAbs / 2, -maxAbs];
      const maxT = Math.log10(1 + maxAbs / RACE_LOG_BASE);
      const ticks = [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]
        .map((v) => v * 1e8)
        .filter((v) => Math.log10(1 + v / RACE_LOG_BASE) <= maxT + 1e-9);
      return ticks.slice().reverse().map((v) => -v).concat([0], ticks);
    }

    function raceTickLabel(value) {
      const yi = value / 1e8;
      if (yi === 0) return '0';
      const abs = Math.abs(yi);
      return (abs >= 10 || Number.isInteger(yi) ? yi.toFixed(0) : yi.toFixed(1)) + '亿';
    }

    const FIELD_COLORS = {
      main_net: '#c0392b',
      super_large_net: '#d35400',
      large_net: '#e67e22',
      mid_net: '#2e86c1',
      small_net: '#8e44ad',
    };
    const INFLOW_SHADES = ['#c0392b', '#b03a2e', '#d35400', '#a93226', '#cb4335'];
    const OUTFLOW_SHADES = ['#1e8449', '#117a65', '#239b56', '#196f3d', '#145a32'];

    function directionColor(index, value) {
      const shades = (value ?? 0) >= 0 ? INFLOW_SHADES : OUTFLOW_SHADES;
      return shades[index % shades.length];
    }

    function SectorRace({ tick }) {
      const [dates, setDates] = useState([]);
      const [date, setDate] = useState('');
      const [field, setField] = useState('main_net');
      const [top, setTop] = useState(20);
      const [speed, setSpeed] = useState(50);
      const [scaleMode, setScaleMode] = useState('log');
      const [view, setView] = useState('race');
      const [data, setData] = useState(null);
      const [grid, setGrid] = useState(null);
      const [page, setPage] = useState(0);
      const [index, setIndex] = useState(0);
      const [playing, setPlaying] = useState(false);
      const [error, setError] = useState(null);
      const [datesLoaded, setDatesLoaded] = useState(false);
      const [nonce, setNonce] = useState(0);
      const [size, setSize] = useState({ w: 900, h: 420 });
      const timer = useRef(null);
      const boxRef = useRef(null);

      useEffect(() => {
        let alive = true;
        fetch(`${API}/api/v1/sector-capital-flows/intraday/dates`, { cache: 'no-store' })
          .then((r) => r.json())
          .then((body) => {
            if (!alive) return;
            const list = body.dates || [];
            setDates(list);
            setDatesLoaded(true);
            if (list.length) setDate((current) => current || list[0]);
          })
          .catch(() => {});
        return () => { alive = false; };
      }, []);

      useEffect(() => {
        const el = boxRef.current;
        if (!el || typeof ResizeObserver === 'undefined') return undefined;
        const measure = (width) => {
          const w = Math.max(560, Math.round(width));
          const h = Math.min(520, Math.max(320, Math.round(w * 0.42)));
          setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
        };
        const observer = new ResizeObserver((entries) => measure(entries[0].contentRect.width));
        observer.observe(el);
        measure(el.getBoundingClientRect().width);
        return () => observer.disconnect();
      }, [datesLoaded, view]);

      useEffect(() => {
        if (!date) return undefined;
        let alive = true;
        const params = new URLSearchParams({ top: String(top), field, trade_date: date });
        fetch(`${API}/api/v1/sector-capital-flows/intraday?${params}`, { cache: 'no-store' })
          .then(async (r) => {
            const body = await r.json();
            if (!r.ok) throw new Error(body?.detail || body?.error || `HTTP ${r.status}`);
            return body;
          })
          .then((body) => {
            if (!alive) return;
            setData(body);
            setIndex(0);
            setPlaying(false);
            setError(null);
          })
          .catch((e) => { if (alive) setError(String(e.message || e)); });
        return () => { alive = false; };
      }, [date, field, top, tick, nonce]);

      // 单板块网格：一次取 5 个资金流字段再按板块合并
      useEffect(() => {
        if (view !== 'grid' || !date) return undefined;
        let alive = true;
        Promise.all(RACE_FIELDS.map(([name]) => {
          const params = new URLSearchParams({ top: String(top), field: name, trade_date: date });
          return fetch(`${API}/api/v1/sector-capital-flows/intraday?${params}`, { cache: 'no-store' })
            .then((r) => (r.ok ? r.json() : null))
            .catch(() => null);
        }))
          .then((results) => {
            if (!alive) return;
            const base = results.find((item) => item && item.times && item.times.length);
            if (!base) { setGrid({ times: [], sectors: [] }); return; }
            const sectors = new Map();
            for (const [name, result] of RACE_FIELDS.map(([fieldName], i) => [fieldName, results[i]])) {
              if (!result || !result.series) continue;
              for (const item of result.series) {
                const entry = sectors.get(item.sector_code) || {
                  code: item.sector_code,
                  name: item.sector_name,
                  values: {},
                };
                entry.values[name] = item.values;
                sectors.set(item.sector_code, entry);
              }
            }
            setGrid({ times: base.times, sectors: [...sectors.values()] });
            setPage(0);
          })
          .catch(() => { if (alive) setGrid({ times: [], sectors: [] }); });
        return () => { alive = false; };
      }, [view, date, top, tick]);

      useEffect(() => {
        if (!playing || !data || !data.times.length) {
          if (timer.current) { clearInterval(timer.current); timer.current = null; }
          return undefined;
        }
        timer.current = setInterval(() => {
          setIndex((current) => Math.min(current + 1, data.times.length - 1));
        }, speed);
        return () => {
          if (timer.current) { clearInterval(timer.current); timer.current = null; }
        };
      }, [playing, speed, data]);

      useEffect(() => {
        if (playing && data && index >= data.times.length - 1) setPlaying(false);
      }, [index, playing, data]);

      const frame = data && data.times.length ? Math.min(index, data.times.length - 1) : 0;

      if (error) return h(ErrorBox, { error, onRetry: () => setNonce((n) => n + 1) });
      if (!datesLoaded) return h(Loading, { text: '加载盘中资金流…' });
      if (!dates.length) {
        return h(Empty, {}, '暂无盘中资金流数据；交易时段每 5 分钟采集一次。');
      }

      const controls = h(
        'div',
        { className: 'iv-row' },
        h('div', { className: 'iv-seg' },
          [['race', '总览曲线'], ['grid', '单板块']].map(([value, label]) =>
            h('button', {
              key: value,
              className: 'iv-seg-btn' + (view === value ? ' on' : ''),
              onClick: () => setView(value),
            }, label)),
        ),
        h('select', { className: 'iv-select', value: date, onChange: (e) => setDate(e.target.value) },
          dates.map((d) => h('option', { key: d, value: d }, d))),
        view === 'race' ? h('select', { className: 'iv-select', value: field, onChange: (e) => setField(e.target.value) },
          RACE_FIELDS.map(([value, label]) => h('option', { key: value, value }, label))) : null,
        h('select', { className: 'iv-select', value: String(top), onChange: (e) => setTop(Number(e.target.value)) },
          [10, 15, 20, 30].map((n) => h('option', { key: n, value: String(n) }, `前 ${n}`))),
        view === 'race' ? h('select', { className: 'iv-select', value: scaleMode, onChange: (e) => setScaleMode(e.target.value) },
          [['log', '对数刻度'], ['linear', '线性刻度']].map(([value, label]) => h('option', { key: value, value }, label))) : null,
        view === 'race' ? h('select', { className: 'iv-select', value: String(speed), onChange: (e) => setSpeed(Number(e.target.value)) },
          [200, 100, 50, 25].map((ms) => h('option', { key: ms, value: String(ms) }, `${200 / ms}x`))) : null,
        view === 'race' ? h('button', {
          className: 'iv-btn' + (playing ? ' on' : ''),
          onClick: () => {
            if (playing) { setPlaying(false); return; }
            if (index >= data.times.length - 1) setIndex(0);
            setPlaying(true);
          },
        }, playing ? '暂停' : '播放') : null,
        view === 'race' ? h('button', { className: 'iv-btn', onClick: () => { setPlaying(false); setIndex(0); } }, '回到开盘') : null,
      );

      if (view === 'grid') {
        const times = grid ? grid.times : [];
        const sectors = grid ? grid.sectors : [];
        const perPage = 6;
        const pageCount = Math.max(1, Math.ceil(sectors.length / perPage));
        const current = Math.min(page, pageCount - 1);
        const visible = sectors.slice(current * perPage, current * perPage + perPage);

        return h(
          'div',
          { className: 'iv-race' },
          controls,
          h('div', { ref: boxRef, style: { width: '100%' } },
            !grid ? h(Loading, { text: '加载单板块数据…' }) : null,
            grid && !times.length ? h(Empty, {}, '该交易日没有盘中资金流数据。') : null,
            grid && times.length
              ? h('div', { className: 'iv-race-grid' }, visible.map((sector) =>
                  h(MiniBoard, { key: sector.code, sector, times })))
              : null,
          ),
          h(
            'div',
            { className: 'iv-pager' },
            h('span', { className: 'iv-muted' }, `共 ${sectors.length} 个板块 · 第 ${current + 1} / ${pageCount} 页`),
            h('button', { className: 'iv-btn', disabled: current === 0, onClick: () => setPage(current - 1) }, '上一页'),
            h('button', { className: 'iv-btn', disabled: current >= pageCount - 1, onClick: () => setPage(current + 1) }, '下一页'),
          ),
          h('div', { className: 'iv-muted', style: { fontSize: 11 } },
            '每个板块一张图：主力/超大/大/中/小五条资金流曲线，显示当日完整走势。数据：东方财富（延迟行情）。'),
        );
      }

      if (!data) return h('div', { className: 'iv-race' }, controls, h(Loading, { text: '加载盘中资金流…' }));
      if (!data.times.length) {
        return h('div', { className: 'iv-race' }, controls, h(Empty, {}, '该交易日没有盘中资金流数据。'));
      }

      const count = data.times.length;
      const series = data.series.map((item) => ({ ...item }));

      let maxAbs = 0;
      for (const item of series) {
        for (const value of item.values) {
          if (value !== null && value !== undefined) maxAbs = Math.max(maxAbs, Math.abs(value));
        }
      }
      maxAbs = maxAbs || 1;
      const maxT = Math.max(Math.abs(raceTransform(maxAbs, scaleMode)), 1e-9);

      const W = size.w;
      const H = size.h;
      const pad = { left: 70, right: 178, top: 18, bottom: 30 };
      const plotW = W - pad.left - pad.right;
      const plotH = H - pad.top - pad.bottom;
      const zeroY = pad.top + plotH / 2;
      const xAt = (i) => pad.left + (count <= 1 ? 0 : (i / (count - 1)) * plotW);
      const yAt = (value) => zeroY - (raceTransform(value, scaleMode) / maxT) * (plotH / 2);
      const ticks = raceTicks(maxAbs, scaleMode);
      const plotRight = pad.left + plotW;

      // 右列标签：按当前值排序后强制最小间距，再用引线连回各自的线端点
      const labelItems = series
        .map((item, i) => ({ name: item.sector_name, value: item.values[frame], index: i }))
        .filter((item) => item.value !== null && item.value !== undefined)
        .sort((a, b) => b.value - a.value);
      const labelYs = labelItems.map((item) =>
        Math.min(pad.top + plotH - 8, Math.max(pad.top + 8, yAt(item.value))));
      for (let i = 1; i < labelYs.length; i += 1) {
        if (labelYs[i] < labelYs[i - 1] + 14) labelYs[i] = labelYs[i - 1] + 14;
      }
      const overflow = labelYs.length ? labelYs[labelYs.length - 1] - (pad.top + plotH - 8) : 0;
      if (overflow > 0) for (let i = 0; i < labelYs.length; i += 1) labelYs[i] -= overflow;

      const paths = series.map((item, i) => {
        const current = item.values[frame];
        const color = directionColor(i, current);
        let d = '';
        let started = false;
        for (let k = 0; k <= frame; k += 1) {
          const value = item.values[k];
          if (value === null || value === undefined) { started = false; continue; }
          d += `${started ? 'L' : 'M'}${xAt(k).toFixed(1)},${yAt(value).toFixed(1)}`;
          started = true;
        }
        return h('g', { key: item.sector_code },
          h('path', { d, fill: 'none', stroke: color, strokeWidth: 1.5, strokeLinejoin: 'round', strokeLinecap: 'round', opacity: 0.85 }),
          current === null || current === undefined ? null
            : h('circle', { cx: xAt(frame), cy: yAt(current), r: 2.4, fill: color }),
        );
      });

      const labelNodes = labelItems.map((item, i) => {
        const y = labelYs[i];
        const color = directionColor(item.index, item.value);
        return h('g', { key: 'label' + item.name },
          h('path', {
            d: `M${plotRight},${yAt(item.value).toFixed(1)}L${plotRight + 12},${y.toFixed(1)}`,
            stroke: color, strokeWidth: 0.8, fill: 'none', opacity: 0.55,
          }),
          h('circle', { cx: plotRight + 12, cy: y, r: 2, fill: color }),
          h('text', {
            x: plotRight + 18, y: y + 3.4, fill: color, fontSize: 10.5,
            stroke: 'var(--dsw-surface-primary,#fff)', strokeWidth: 3, paintOrder: 'stroke',
          }, `${item.name} ${(item.value / 1e8).toFixed(1)}亿`),
        );
      });

      return h(
        'div',
        { className: 'iv-race' },
        controls,
        h(
          'div',
          { className: 'iv-race-clock' },
          h('b', {}, data.times[frame]),
          h('input', {
            className: 'iv-race-progress',
            type: 'range',
            min: 0,
            max: count - 1,
            value: frame,
            onChange: (e) => { setPlaying(false); setIndex(Number(e.target.value)); },
          }),
          h('span', {}, `${frame + 1} / ${count}`),
        ),
        h('div', { ref: boxRef, style: { width: '100%' } },
          h('svg', {
            viewBox: `0 0 ${W} ${H}`,
            style: { width: '100%', height: H + 'px', display: 'block' },
            role: 'img',
          },
            ticks.map((value, i) => h('g', { key: 'tick' + i },
              h('line', {
                x1: pad.left, x2: plotRight, y1: yAt(value), y2: yAt(value),
                stroke: value === 0 ? 'var(--dsw-border-default,#c9ccd2)' : 'var(--dsw-border-subtle,#eceef2)',
                strokeWidth: value === 0 ? 1.2 : 1,
              }),
              h('text', {
                x: pad.left - 8, y: yAt(value) + 3, textAnchor: 'end', fontSize: 10,
                fill: 'var(--dsw-text-tertiary,#8a9099)',
              }, raceTickLabel(value)),
            )),
            [0, Math.floor(count / 4), Math.floor(count / 2), Math.floor((count * 3) / 4), count - 1]
              .filter((v, i, arr) => arr.indexOf(v) === i)
              .map((i) => h('text', {
                key: 'x' + i, x: xAt(i), y: H - 8, textAnchor: 'middle', fontSize: 10,
                fill: 'var(--dsw-text-tertiary,#8a9099)',
              }, data.times[i])),
            h('line', {
              x1: xAt(frame), x2: xAt(frame), y1: pad.top, y2: pad.top + plotH,
              stroke: 'var(--dsw-text-tertiary,#8a9099)', strokeWidth: 1, strokeDasharray: '3 3',
            }),
            paths,
            labelNodes,
          ),
        ),
        h('div', { className: 'iv-muted', style: { fontSize: 11 } },
          `每条线一个板块，零轴上方净流入（红）、下方净流出（绿）；共 ${series.length} 个板块。`,
          scaleMode === 'log' ? '纵轴为对数刻度（1 亿基准的对称 log）。' : '纵轴为线性刻度。',
          '数据：东方财富（延迟行情）。'),
      );
    }

    function MiniBoard({ sector, times }) {
      const W = 360;
      const H = 150;
      const pad = { left: 8, right: 52, top: 10, bottom: 14 };
      const plotW = W - pad.left - pad.right;
      const plotH = H - pad.top - pad.bottom;
      const zeroY = pad.top + plotH / 2;
      const count = times.length;
      let maxAbs = 0;
      for (const [, name] of RACE_FIELDS) {
        for (const value of sector.values[name] || []) {
          if (value !== null && value !== undefined) maxAbs = Math.max(maxAbs, Math.abs(value));
        }
      }
      maxAbs = maxAbs || 1;
      const xAt = (i) => pad.left + (count <= 1 ? 0 : (i / (count - 1)) * plotW);
      const yAt = (value) => zeroY - (value / maxAbs) * (plotH / 2);

      const mainValues = sector.values.main_net || [];
      const last = [...mainValues].reverse().find((v) => v !== null && v !== undefined) ?? 0;

      return h('div', { className: 'iv-mini' },
        h('div', { className: 'iv-mini-head' },
          h('strong', {}, sector.name),
          h('span', { className: toneOf(last) }, (last / 1e8).toFixed(2) + '亿'),
        ),
        h('svg', {
          viewBox: `0 0 ${W} ${H}`,
          style: { width: '100%', height: 'auto', display: 'block' },
          role: 'img',
        },
          h('line', {
            x1: pad.left, x2: pad.left + plotW, y1: zeroY, y2: zeroY,
            stroke: 'var(--dsw-border-default,#c9ccd2)', strokeWidth: 1,
          }),
          RACE_FIELDS.map(([name]) => {
            const values = sector.values[name] || [];
            let d = '';
            let started = false;
            for (let i = 0; i < values.length; i += 1) {
              const value = values[i];
              if (value === null || value === undefined) { started = false; continue; }
              d += `${started ? 'L' : 'M'}${xAt(i).toFixed(1)},${yAt(value).toFixed(1)}`;
              started = true;
            }
            return h('path', {
              key: name,
              d,
              fill: 'none',
              stroke: FIELD_COLORS[name],
              strokeWidth: name === 'main_net' ? 1.6 : 1.1,
              opacity: name === 'main_net' ? 0.95 : 0.7,
              strokeLinejoin: 'round',
            });
          }),
        ),
        h('div', { className: 'iv-mini-legend' },
          RACE_FIELDS.map(([name, label]) => {
            const values = sector.values[name] || [];
            const value = [...values].reverse().find((v) => v !== null && v !== undefined) ?? 0;
            return h('span', { key: name },
              h('i', { style: { background: FIELD_COLORS[name] } }),
              `${label} ${(value / 1e8).toFixed(2)}亿`);
          }),
        ),
      );
    }

    /* ------------------------------------------------------------------ 面板 */

    const TABS = [
      ['overview', '总览'],
      ['watchlist', '自选'],
      ['portfolios', '组合'],
      ['flows', '板块资金流'],
      ['race', '资金流回放'],
    ];

    function Panel() {
      useStyle();
      const [tab, setTab] = useState('overview');
      const [tick, setTick] = useState(0);
      const [status, setStatus] = useState(null);

      const refresh = useCallback(() => {
        quoteCache.clear();
        setTick((t) => t + 1);
      }, []);

      useEffect(() => {
        let alive = true;
        const load = () => {
          getJson('/status')
            .then((s) => alive && setStatus(s))
            .catch((e) => alive && setStatus({ reachable: false, error: String(e.message || e) }));
        };
        load();
        const timer = setInterval(load, 30_000);
        return () => {
          alive = false;
          clearInterval(timer);
        };
      }, []);

      const state = status
        ? status.reachable ? 'ok' : 'bad'
        : '';
      const label = status
        ? status.reachable
          ? `已连接 ${status.upstream.replace(/^https?:\/\//, '')}`
          : 'invest 服务未连接'
        : '连接中…';

      return h(
        'div',
        { className: 'iv-root' },
        h(
          'div',
          { className: 'iv-head' },
          h('div', { className: 'iv-title' },
            h('span', { className: 'iv-dot ' + state }),
            '投资',
          ),
          h('span', { className: 'iv-muted' }, label),
          h('div', { className: 'iv-spacer' }),
          h('button', { className: 'iv-btn', onClick: refresh, title: '重新取数' }, '刷新'),
        ),
        h(
          'div',
          { className: 'iv-tabs' },
          TABS.map(([id, name]) => h(
            'button',
            { key: id, className: 'iv-tab' + (tab === id ? ' on' : ''), onClick: () => setTab(id) },
            name,
          )),
        ),
        h(
          'div',
          { className: 'iv-body' },
          tab === 'overview' ? h(Overview, { tick, go: refresh }) : null,
          tab === 'watchlist' ? h(Watchlist, { tick }) : null,
          tab === 'portfolios' ? h(Portfolios, { tick }) : null,
          tab === 'flows' ? h(SectorFlows, { tick }) : null,
          tab === 'race' ? h(SectorRace, { tick }) : null,
        ),
      );
    }

    function Icon({ size = 18, active }) {
      return h('svg', {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: active ? 1.9 : 1.6,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
      },
        h('path', { d: 'M3 20V4' }),
        h('path', { d: 'M3 20h18' }),
        h('path', { d: 'M7 16l4-5 3 3 4-6' }),
        h('circle', { cx: 7, cy: 16, r: 1.1 }),
        h('circle', { cx: 18, cy: 8, r: 1.1 }),
      );
    }

    function apply(ctx) {
      ctx.slots.inject('main', function* () {
        yield ctx.slots.register({ name: 'main', key: PANEL_ID }, () => h(Panel, {}));
      });
      ctx.slots.inject('sidebar.panellist', function* () {
        yield ctx.slots.register(
          { name: 'sidebar.panellist', id: PANEL_ID, order: 31, label: () => '投资' },
          Icon,
        );
      });
    }

    module.exports = { name: 'dsh-invest', inject: ['slots'], apply };
    return module.exports;
  },
});
