/* LC AutoSync OAuth state helpers (no secrets, no network).
 *
 * Loaded as a plain script in popup.html (global `LCAuth`) and directly in
 * node for tests. All storage access goes through a small promise-based area
 * adapter so the same logic runs in the browser and in tests:
 *
 *   area.get(key)    -> Promise<value|undefined>
 *   area.set(key, v) -> Promise<void>
 *   area.remove(key) -> Promise<void>
 *
 * State entries are { value, expiresAt } — short-lived (5 min) and single-use:
 * consumePendingState() deletes the entry before returning it.
 */
(function (root) {
  'use strict';

  var STATE_KEY = 'oauth_state_pending';
  var STATE_TTL_MS = 5 * 60 * 1000;
  var STATE_BYTES = 16;

  function getCrypto() {
    if (root.crypto && root.crypto.getRandomValues) return root.crypto;
    // node fallback (tests): require('crypto').webcrypto
    try {
      // eslint-disable-next-line no-undef
      var nodeCrypto = require('crypto');
      if (nodeCrypto.webcrypto && nodeCrypto.webcrypto.getRandomValues) return nodeCrypto.webcrypto;
    } catch (_) { /* ignore */ }
    throw new Error('No secure random number generator available');
  }

  function base64Url(bytes) {
    var bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    var b64 = (typeof btoa !== 'undefined') ? btoa(bin) : Buffer.from(bin, 'binary').toString('base64');
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  /** Cryptographically random, URL-safe state string. */
  function generateState(numBytes) {
    var n = numBytes || STATE_BYTES;
    var bytes = new Uint8Array(n);
    getCrypto().getRandomValues(bytes);
    return base64Url(bytes);
  }

  /** Build the GitHub authorize URL (redirect URI + state always included). */
  function buildAuthUrl(opts) {
    if (!opts || !opts.clientId || !opts.redirectUri || !opts.state) {
      throw new Error('clientId, redirectUri and state are required');
    }
    var scope = opts.scope || 'repo';
    return 'https://github.com/login/oauth/authorize'
      + '?client_id=' + encodeURIComponent(opts.clientId)
      + '&redirect_uri=' + encodeURIComponent(opts.redirectUri)
      + '&scope=' + encodeURIComponent(scope)
      + '&state=' + encodeURIComponent(opts.state);
  }

  /** Parse the OAuth redirect URL. Throws on missing code/state (never logs values). */
  function parseCallback(url) {
    var u;
    try {
      u = new URL(url);
    } catch (_) {
      throw new Error('Invalid OAuth callback URL');
    }
    var code = u.searchParams.get('code');
    var state = u.searchParams.get('state');
    if (!code) throw new Error('OAuth callback missing authorization code');
    if (!state) throw new Error('OAuth callback missing state');
    return { code: code, state: state };
  }

  function savePendingState(area, state) {
    return area.set(STATE_KEY, { value: state, expiresAt: Date.now() + STATE_TTL_MS });
  }

  /**
   * Single-use read: returns the stored entry (or null when missing/expired)
   * and deletes it so it cannot be replayed.
   */
  function consumePendingState(area) {
    return area.get(STATE_KEY).then(function (entry) {
      return area.remove(STATE_KEY).then(function () { return entry || null; });
    }).then(function (entry) {
      if (!entry || !entry.value || !entry.expiresAt) return null;
      if (Date.now() > entry.expiresAt) return null;
      return entry;
    });
  }

  /**
   * Full validation: parse callback, consume stored state single-use, compare.
   * Resolves with the authorization code; rejects on missing/mismatched/
   * expired state. Values are never written to logs here — throw messages
   * describe the failure class only.
   */
  async function validateCallback(area, callbackUrl) {
    var parsed = parseCallback(callbackUrl);
    var entry = await consumePendingState(area);
    if (!entry) throw new Error('OAuth state missing or expired. Please try connecting again.');
    if (entry.value !== parsed.state) throw new Error('OAuth state mismatch. Please try connecting again.');
    return parsed.code;
  }

  root.LCAuth = {
    STATE_TTL_MS: STATE_TTL_MS,
    generateState: generateState,
    buildAuthUrl: buildAuthUrl,
    parseCallback: parseCallback,
    savePendingState: savePendingState,
    consumePendingState: consumePendingState,
    validateCallback: validateCallback
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
