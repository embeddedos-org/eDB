// SPDX-License-Identifier: MIT
// Smoke tests for the eDB React frontend.
// These exercise the public API surface of each component/hook so that
// rename/removal regressions are caught even without UI snapshots.
import { describe, it, expect } from 'vitest';

describe('eDB frontend smoke', () => {
  it('hook module exports useDatabase', async () => {
    const mod = await import('../hooks/useDatabase');
    expect(typeof mod.useDatabase).toBe('function');
  });

  it('hook module exports useEBot', async () => {
    const mod = await import('../hooks/useEBot');
    expect(typeof mod.useEBot).toBe('function');
  });

  it.each([
    ['EBotSidebar', 'EBotSidebar'],
    ['QueryEditor', 'QueryEditor'],
    ['StatusBar',   'StatusBar'],
    ['TableList',   'TableList'],
    ['TableView',   'TableView'],
    ['TopBar',      'TopBar'],
  ])('component %s exports a default React component', async (name) => {
    const mod = await import(`../components/${name}`);
    expect(mod.default).toBeDefined();
  });
});
