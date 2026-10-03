importScripts('config.js');

chrome.runtime.onInstalled.addListener(() => {
  console.log("LC AutoSync installed");
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'get-config') {
    chrome.storage.local.get(['github_token', 'github_user', 'repo_owner', 'repo_name', 'branch', 'auto_sync'], (data) => {
      sendResponse(data);
    });
    return true; // Required for async response
  }

  if (message.type === 'get-auth-status') {
    chrome.storage.local.get(['github_token', 'github_user', 'repo_owner', 'onboarding_complete'], (data) => {
      sendResponse({
        authenticated: !!data.github_token,
        user: data.github_user || null,
        configured: !!data.onboarding_complete
      });
    });
    return true;
  }

  if (message.type === 'disconnect-github') {
    chrome.storage.local.remove(['github_token', 'github_user', 'repo_owner', 'repo_name', 'branch', 'auto_sync', 'onboarding_complete'], () => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (message.type === 'auth-complete') {
    chrome.storage.local.set({
      github_token: message.payload.token,
      github_user: message.payload.user,
      auto_sync: true
    }, () => {
      sendResponse({ success: true });
    });
    return true;
  }
});
