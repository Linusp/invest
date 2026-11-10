// 宿主半侧集成测试：用替身 ctx 跑 apply()，确认路由确实注册且能转发。
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { apply } from '../lib/index.js';

let server;
let base;

before(async () => {
  const routes = [];
  const ctx = {
    webServer: { register: (route) => { routes.push(route); return () => {}; } },
    effect: (fn) => { fn(); },
  };
  apply(ctx, { baseUrl: 'http://127.0.0.1:8001', prefix: '/dsh-invest' });
  assert.equal(routes.length, 1, '应当注册一条路由');
  assert.equal(routes[0].kind, 'prefix');
  assert.equal(routes[0].path, '/dsh-invest');

  server = createServer(routes[0].handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

after(() => new Promise((resolve) => server.close(resolve)));

test('注册的路由能返回 invest 数据', async () => {
  const res = await fetch(`${base}/dsh-invest/api/v1/assets`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.ok(Array.isArray(body));
});

test('prefix 之外的请求不归它管', async () => {
  const res = await fetch(`${base}/other/api/v1/assets`);
  assert.equal(res.status, 404);
});
