// 代理冒烟测试：需要本地 invest 服务在 127.0.0.1:8001 上运行。
// 运行：node --test test/proxy.test.mjs
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { makeInvestProxy } from '../lib/proxy.js';

const PREFIX = '/dsh-invest';
let server;
let base;

before(async () => {
  server = createServer(makeInvestProxy({ baseUrl: 'http://127.0.0.1:8001', prefix: PREFIX }));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

after(() => new Promise((resolve) => server.close(resolve)));

test('status 报告上游可达', async () => {
  const res = await fetch(`${base}${PREFIX}/status`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.reachable, true);
  assert.equal(body.upstream, 'http://127.0.0.1:8001');
});

test('转发 /api/v1 查询串与 JSON', async () => {
  const res = await fetch(`${base}${PREFIX}/api/v1/sector-capital-flows?limit=2`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-type'), /application\/json/);
  const body = await res.json();
  assert.ok('count' in body);
});

test('非 API 路径返回 404', async () => {
  const res = await fetch(`${base}${PREFIX}/nope`);
  assert.equal(res.status, 404);
});

test('路径穿越不会逃出白名单', async () => {
  const res = await fetch(`${base}${PREFIX}/api/../../etc/passwd`);
  assert.equal(res.status, 404);
});
