// 同源反向代理：/dsh-invest/api/v1/* → ${baseUrl}/api/v1/*
//
// 浏览器半侧只跟 DSH 自己的 webServer 说话，因此绕开了 invest 服务的 CORS 配置，
// 也不需要把 127.0.0.1:8001 暴露给页面。

const DEFAULT_TIMEOUT_MS = 20_000;
const PROBE_TIMEOUT_MS = 3_000;

/** 允许转发的上游路径前缀；其余一律 404，避免变成任意 URL 代理。 */
const ALLOWED_UPSTREAM_PREFIXES = ['/api/', '/health'];

function sendJson(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(text),
  });
  res.end(text);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks);
}

function isAllowed(rest) {
  const path = rest.split('?')[0];
  return ALLOWED_UPSTREAM_PREFIXES.some((p) => path.startsWith(p));
}

/**
 * @param {{baseUrl: string, prefix: string, timeoutMs?: number, log?: (...a: unknown[]) => void}} options
 * @returns {(req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse) => Promise<void>}
 */
export function makeInvestProxy({ baseUrl, prefix, timeoutMs = DEFAULT_TIMEOUT_MS, log = () => {} }) {
  const upstream = String(baseUrl).replace(/\/+$/, '');
  const basePath = String(prefix).replace(/\/+$/, '');

  async function probe() {
    const started = Date.now();
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), PROBE_TIMEOUT_MS);
    try {
      const res = await fetch(`${upstream}/health`, { signal: ac.signal });
      return { ok: res.ok, status: res.status, latencyMs: Date.now() - started };
    } catch (error) {
      return { ok: false, error: String(error), latencyMs: Date.now() - started };
    } finally {
      clearTimeout(timer);
    }
  }

  return async function handler(req, res) {
    const url = new URL(req.url ?? '/', 'http://localhost');

    if (!url.pathname.startsWith(basePath)) {
      return sendJson(res, 404, { error: 'not found' });
    }

    const rest = url.pathname.slice(basePath.length) || '/';

    if (rest === '/status' || rest === '/status/') {
      const health = await probe();
      return sendJson(res, 200, { upstream, prefix: basePath, reachable: health.ok, health });
    }

    if (!isAllowed(rest)) {
      return sendJson(res, 404, { error: 'not found' });
    }

    const target = `${upstream}${rest}${url.search}`;
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);

    try {
      const method = (req.method ?? 'GET').toUpperCase();
      const hasBody = method !== 'GET' && method !== 'HEAD';
      const body = hasBody ? await readBody(req) : undefined;
      const headers = {};
      if (req.headers['content-type']) headers['content-type'] = req.headers['content-type'];
      headers.accept = 'application/json';

      const upstreamRes = await fetch(target, { method, headers, body, signal: ac.signal });
      const buffer = Buffer.from(await upstreamRes.arrayBuffer());
      res.writeHead(upstreamRes.status, {
        'content-type': upstreamRes.headers.get('content-type') ?? 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        'content-length': buffer.length,
      });
      res.end(buffer);
    } catch (error) {
      log('proxy failed:', target, error);
      sendJson(res, 502, {
        error: 'invest service unreachable',
        upstream,
        detail: String(error),
      });
    } finally {
      clearTimeout(timer);
    }
  };
}
