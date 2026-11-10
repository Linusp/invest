// 宿主半侧：只注册一个同源代理路由，挂在 DSH 的 webServer 上。
import { makeInvestProxy } from './proxy.js';

export const name = 'dsh-invest';
export const inject = ['webServer'];

const log = (...args) => console.log('[invest]', ...args);

export function apply(ctx, config = {}) {
  const baseUrl = config.baseUrl || 'http://127.0.0.1:8001';
  const prefix = (config.prefix || '/dsh-invest').replace(/\/+$/, '');

  if (typeof ctx.webServer?.register !== 'function') {
    log('webServer 不可用：不注册 HTTP 路由');
    return;
  }

  const handler = makeInvestProxy({ baseUrl, prefix, log });

  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: prefix, handler }),
    'dsh-invest: routes',
  );

  log(`${prefix} -> ${baseUrl}`);
}
