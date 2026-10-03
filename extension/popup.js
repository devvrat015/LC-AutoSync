document.addEventListener('DOMContentLoaded', async () => {
  // --- View Management ---
  const views = {
    connect: document.getElementById('view-connect'),
    setup: document.getElementById('view-setup'),
    dashboard: document.getElementById('view-dashboard'),
    loading: document.getElementById('view-loading')
  };

  function showView(viewName) {
    Object.values(views).forEach(v => v.classList.add('hidden'));
    if (views[viewName]) {
      views[viewName].classList.remove('hidden');
    }
  }

  function showError(msg) {
    const errorEl = document.getElementById('global-error');
    document.getElementById('error-text').textContent = msg;
    errorEl.classList.remove('hidden');
  }

  document.getElementById('btn-error-close').addEventListener('click', () => {
    document.getElementById('global-error').classList.add('hidden');
  });

  // --- Initialization ---
  async function init() {
    showView('loading');
    chrome.runtime.sendMessage({ type: 'get-auth-status' }, (status) => {
      if (chrome.runtime.lastError) {
        showError("Failed to communicate with extension background.");
        showView('connect');
        return;
      }
      
      if (!status.authenticated) {
        showView('connect');
      } else if (!status.configured) {
        setupSetupView(status.user);
      } else {
        setupDashboardView();
      }
    });
  }

  // --- Connect View ---
  // Short-lived session storage for the OAuth state nonce (MV3-friendly,
  // cleared when the browser closes). Falls back to local on old Chrome.
  function stateArea() {
    function wrap(area) {
      return {
        get: (k) => new Promise((resolve) => area.get([k], (o) => resolve(o && o[k]))),
        set: (k, v) => new Promise((resolve) => area.set({ [k]: v }, resolve)),
        remove: (k) => new Promise((resolve) => area.remove([k], resolve))
      };
    }
    if (chrome.storage.session) return wrap(chrome.storage.session);
    return wrap(chrome.storage.local);
  }

  document.getElementById('btn-connect').addEventListener('click', async () => {
    showView('loading');
    document.getElementById('loading-text').textContent = 'Authenticating...';

    try {
      const redirectUri = chrome.identity.getRedirectURL();
      // OAuth scope "repo" is the minimum that covers private repositories
      // (read/write code + README). Public-only users could use "public_repo",
      // but GitHub OAuth Apps cannot be scoped to a single repo — a GitHub App
      // would be needed for that. The scope is shown by GitHub at consent time.
      const oauthState = LCAuth.generateState();
      await LCAuth.savePendingState(stateArea(), oauthState);
      const authUrl = LCAuth.buildAuthUrl({
        clientId: LC_CONFIG.GITHUB_CLIENT_ID,
        redirectUri,
        scope: 'repo',
        state: oauthState
      });

      const responseUrl = await new Promise((resolve, reject) => {
        chrome.identity.launchWebAuthFlow({ url: authUrl, interactive: true }, (url) => {
          if (chrome.runtime.lastError || !url) {
            reject(new Error(chrome.runtime.lastError?.message || 'Authentication cancelled'));
          } else {
            resolve(url);
          }
        });
      });

      // Validates state (single-use, 5-min expiry) before the code is touched.
      const code = await LCAuth.validateCallback(stateArea(), responseUrl);

      const tokenRes = await fetch(`${LC_CONFIG.SERVICE_URL}/auth/github/exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Same redirect URI as the authorize request above; the backend
        // forwards it to GitHub so both halves of the flow agree.
        body: JSON.stringify({ code, redirect_uri: redirectUri })
      });
      if (!tokenRes.ok) throw new Error(`Token exchange failed: ${tokenRes.status}`);
      const { access_token } = await tokenRes.json();
      if (!access_token) throw new Error("No access token returned from server");

      const userRes = await fetch(`${LC_CONFIG.SERVICE_URL}/github/user`, {
        headers: { 'Authorization': `Bearer ${access_token}` }
      });
      if (!userRes.ok) throw new Error("Failed to fetch GitHub user info");
      const user = await userRes.json();

      chrome.runtime.sendMessage({
        type: 'auth-complete',
        payload: { token: access_token, user }
      }, (res) => {
        setupSetupView(user);
      });

    } catch (err) {
      console.error(err);
      showError(err.message || 'Authentication failed');
      showView('connect');
    }
  });

  // --- Setup View ---
  const repoSelect = document.getElementById('repo-select');
  const branchSelect = document.getElementById('branch-select');
  const btnSave = document.getElementById('btn-save');
  let currentToken = null;
  let reposList = [];

  async function setupSetupView(user) {
    showView('setup');
    document.getElementById('setup-avatar').src = user.avatar_url || '';
    document.getElementById('setup-username').textContent = user.login;
    
    repoSelect.innerHTML = '<option value="" disabled selected>Loading repositories...</option>';
    repoSelect.disabled = true;
    branchSelect.disabled = true;
    btnSave.disabled = true;

    try {
      const data = await new Promise(resolve => chrome.storage.local.get(['github_token'], resolve));
      currentToken = data.github_token;
      
      const res = await fetch(`${LC_CONFIG.SERVICE_URL}/github/repos`, {
        headers: { 'Authorization': `Bearer ${currentToken}` }
      });
      if (!res.ok) throw new Error("Failed to load repositories");
      reposList = await res.json();
      
      repoSelect.innerHTML = '<option value="" disabled selected>Select a repository</option>';
      reposList.forEach(repo => {
        const opt = document.createElement('option');
        opt.value = repo.full_name; // owner/repo
        opt.textContent = repo.full_name;
        repoSelect.appendChild(opt);
      });
      repoSelect.disabled = false;
      
    } catch (err) {
      console.error(err);
      document.getElementById('setup-error').textContent = err.message;
      document.getElementById('setup-error').classList.remove('hidden');
      repoSelect.innerHTML = '<option value="" disabled>Error loading repos</option>';
    }
  }

  repoSelect.addEventListener('change', async () => {
    const fullName = repoSelect.value;
    const [owner, repoName] = fullName.split('/');
    
    branchSelect.innerHTML = '<option value="" disabled selected>Loading branches...</option>';
    branchSelect.disabled = true;
    btnSave.disabled = true;

    try {
      const res = await fetch(`${LC_CONFIG.SERVICE_URL}/github/repos/${owner}/${repoName}/branches`, {
        headers: { 'Authorization': `Bearer ${currentToken}` }
      });
      if (!res.ok) throw new Error("Failed to load branches");
      const branches = await res.json();
      
      const repoObj = reposList.find(r => r.full_name === fullName);
      const defaultBranch = repoObj ? repoObj.default_branch : 'main';

      branchSelect.innerHTML = '';
      branches.forEach(b => {
        const opt = document.createElement('option');
        opt.value = b.name;
        opt.textContent = b.name;
        if (b.name === defaultBranch) opt.selected = true;
        branchSelect.appendChild(opt);
      });
      branchSelect.disabled = false;
      btnSave.disabled = false;

    } catch (err) {
      console.error(err);
      branchSelect.innerHTML = '<option value="" disabled>Error loading branches</option>';
    }
  });

  btnSave.addEventListener('click', () => {
    const fullName = repoSelect.value;
    const branch = branchSelect.value;
    if (!fullName || !branch) return;
    const [owner, repoName] = fullName.split('/');

    chrome.storage.local.set({
      repo_owner: owner,
      repo_name: repoName,
      branch: branch,
      onboarding_complete: true
    }, () => {
      setupDashboardView();
    });
  });

  // --- Dashboard View ---
  const toggleSync = document.getElementById('toggle-sync');
  const settingsSection = document.getElementById('settings-section');
  
  async function setupDashboardView() {
    showView('loading');
    chrome.runtime.sendMessage({ type: 'get-config' }, (config) => {
      if (!config) {
        showError("Failed to load configuration");
        return;
      }
      
      if (config.github_user) {
        document.getElementById('dash-avatar').src = config.github_user.avatar_url || '';
        document.getElementById('dash-username').textContent = config.github_user.login;
      }
      
      document.getElementById('dash-repo-info').textContent = `${config.repo_owner}/${config.repo_name} @ ${config.branch}`;
      toggleSync.checked = config.auto_sync !== false; // true by default
      
      settingsSection.classList.add('hidden');
      showView('dashboard');
    });
  }

  document.getElementById('btn-settings-toggle').addEventListener('click', () => {
    settingsSection.classList.toggle('hidden');
  });

  toggleSync.addEventListener('change', () => {
    chrome.storage.local.set({ auto_sync: toggleSync.checked });
  });

  document.getElementById('btn-change-repo').addEventListener('click', () => {
    chrome.storage.local.get(['github_user'], (data) => {
      setupSetupView(data.github_user);
    });
  });

  document.getElementById('btn-disconnect').addEventListener('click', () => {
    // Local-only disconnect: removes the token from this browser so syncing
    // stops. It does NOT revoke the grant on github.com — the user can do that
    // at Settings → Applications → Authorized OAuth Apps if desired.
    if (confirm("Disconnect GitHub on this device? This removes the local connection and stops auto-syncing. (To fully revoke access, also visit GitHub Settings → Applications.)")) {
      chrome.runtime.sendMessage({ type: 'disconnect-github' }, () => {
        init();
      });
    }
  });

  // Start app
  init();
});
