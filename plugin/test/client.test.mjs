// 客户端 bundle 契约测试：用替身 __ModuleLoader__ 加载 lib/client.js，
// 确认它导出了 apply，并往 main / sidebar.panellist 两个槽位各注册一次。
import { test } from 'node:test';
import assert from 'node:assert/strict';

let loaded;

globalThis.window = {
  __ModuleLoader__: {
    load: ({ id, factory }) => {
      const requireMock = (name) => {
        if (name === 'react') return {};
        if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }) };
        throw new Error('unexpected require: ' + name);
      };
      loaded = { id, module: factory(requireMock) };
    },
  },
};

await import('../lib/client.js');

test('注册为 web 客户端插件', () => {
  assert.ok(loaded, '__ModuleLoader__.load 未被调用');
  assert.equal(loaded.id, 'dsh-invest');
  assert.equal(loaded.module.name, 'dsh-invest');
  assert.deepEqual(loaded.module.inject, ['slots']);
  assert.equal(typeof loaded.module.apply, 'function');
});

test('apply 往 main 与 sidebar.panellist 注册面板', () => {
  const registrations = [];
  const ctx = {
    slots: {
      inject: (slot, generator) => {
        for (const value of generator()) registrations.push({ slot, value });
      },
      register: (options, component) => ({ options, component }),
    },
  };

  loaded.module.apply(ctx);

  assert.equal(registrations.length, 2);
  assert.deepEqual(registrations.map((r) => r.slot), ['main', 'sidebar.panellist']);
  assert.equal(registrations[0].value.options.key, 'invest');
  assert.equal(registrations[1].value.options.id, 'invest');
  assert.equal(registrations[1].value.options.label(), '投资');
  assert.equal(typeof registrations[0].value.component, 'function');
  assert.equal(typeof registrations[1].value.component, 'function');
});
