/* OAuth state tests — node, no dependencies.
 * Run: node --test test_oauth_state.js   (from extension/)
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

require('./oauth_state.js');
const { LCAuth } = globalThis;

function memArea() {
  const m = new Map();
  return {
    get: async (k) => m.get(k),
    set: async (k, v) => { m.set(k, v); },
    remove: async (k) => { m.delete(k); },
  };
}

function callbackUrl(code, state) {
  const u = 'https://x.chromiumapp.org/?code=' + encodeURIComponent(code);
  return state === undefined ? u : u + '&state=' + encodeURIComponent(state);
}

describe('generateState', () => {
  it('is URL-safe and unique', () => {
    const a = LCAuth.generateState();
    const b = LCAuth.generateState();
    assert.match(a, /^[A-Za-z0-9_-]+$/);
    assert.ok(a.length >= 20, 'enough entropy (>=16 bytes)');
    assert.notEqual(a, b);
  });
});

describe('buildAuthUrl', () => {
  it('includes client_id, redirect_uri, scope and state', () => {
    const url = LCAuth.buildAuthUrl({
      clientId: 'CID', redirectUri: 'https://abc.chromiumapp.org/', scope: 'repo', state: 's1',
    });
    assert.ok(url.startsWith('https://github.com/login/oauth/authorize?'));
    assert.ok(url.includes('client_id=CID'));
    assert.ok(url.includes('redirect_uri=' + encodeURIComponent('https://abc.chromiumapp.org/')));
    assert.ok(url.includes('scope=repo'));
    assert.ok(url.includes('state=s1'));
  });

  it('rejects missing fields (never hardcodes an extension id)', () => {
    assert.throws(() => LCAuth.buildAuthUrl({ clientId: 'x', redirectUri: 'y' }), /state/);
  });
});

describe('validateCallback', () => {
  it('accepts a valid state and returns the code (single-use)', async () => {
    const area = memArea();
    await LCAuth.savePendingState(area, 'good-state');
    const code = await LCAuth.validateCallback(area, callbackUrl('AUTHCODE', 'good-state'));
    assert.equal(code, 'AUTHCODE');
    // Replayed callback must now fail: entry was consumed.
    await assert.rejects(LCAuth.validateCallback(area, callbackUrl('AUTHCODE', 'good-state')), /missing or expired/);
  });

  it('rejects a missing callback state', async () => {
    const area = memArea();
    await LCAuth.savePendingState(area, 's');
    await assert.rejects(LCAuth.validateCallback(area, callbackUrl('C')), /missing state/);
  });

  it('rejects an incorrect state', async () => {
    const area = memArea();
    await LCAuth.savePendingState(area, 'expected');
    await assert.rejects(
      LCAuth.validateCallback(area, callbackUrl('C', 'attacker')),
      /mismatch/
    );
  });

  it('rejects when nothing was stored (e.g. fresh popup)', async () => {
    await assert.rejects(LCAuth.validateCallback(memArea(), callbackUrl('C', 's')), /missing or expired/);
  });

  it('rejects expired state', async () => {
    const m = new Map();
    const area = {
      get: async (k) => m.get(k),
      set: async (k, v) => { m.set(k, v); },
      remove: async (k) => { m.delete(k); },
    };
    await area.set('oauth_state_pending', { value: 'old', expiresAt: Date.now() - 1000 });
    await assert.rejects(LCAuth.validateCallback(area, callbackUrl('C', 'old')), /missing or expired/);
  });

  it('rejects a missing authorization code', async () => {
    const area = memArea();
    await LCAuth.savePendingState(area, 's');
    await assert.rejects(LCAuth.validateCallback(area, 'https://x/?state=s'), /missing authorization code/);
  });
});
