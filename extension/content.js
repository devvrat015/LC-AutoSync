/* LeetCode Auto-Sync — content script
 *
 * Flow: MutationObserver sees "Accepted" -> scrape code -> GraphQL metadata
 *       -> parse runtime/memory from the result panel -> POST to localhost:7337
 */

const SERVICE_URL = "https://lc-auto-sync.vercel.app/submit";

let processed = false;
let observer = null;

/* ----------------------------------------------------------- helpers */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function currentSlug() {
  const m = window.location.pathname.match(/\/problems\/([^/]+)/);
  return m ? m[1] : null;
}

/** Wait for fn() to return a truthy value, polling until timeout. */
async function waitFor(fn, timeoutMs = 4000, intervalMs = 150) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = fn();
    if (value) return value;
    await sleep(intervalMs);
  }
  return null;
}

/* ----------------------------------------------------------- detection */

function isAccepted() {
  const node = document.querySelector('[data-e2e-locator="submission-result"]');
  if (node && /accepted/i.test(node.textContent)) return true;

  // Fallback: LeetCode occasionally renders the verdict without that attribute.
  return Array.from(document.querySelectorAll("span, div")).some(
    (el) => el.children.length === 0 && el.textContent.trim() === "Accepted"
  );
}

/* ----------------------------------------------------------- scraping */

function scrapeCode() {
  const lines = document.querySelectorAll(".view-lines .view-line");
  if (lines.length) {
    // Monaco renders lines in arbitrary DOM order and positions them with
    // `top`. Sort by that, otherwise the file comes out scrambled.
    return Array.from(lines)
      .map((el) => ({
        top: parseInt(el.style.top, 10) || 0,
        text: el.innerText.replace(/\u00a0/g, " ").replace(/\s+$/, ""),
      }))
      .sort((a, b) => a.top - b.top)
      .map((l) => l.text)
      .join("\n")
      .trimEnd();
  }

  const textarea = document.querySelector("textarea.inputarea");
  return textarea ? textarea.value.trimEnd() : "";
}

async function fetchMetadata(slug) {
  const query = `
    query questionData($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        questionId
        questionFrontendId
        title
        titleSlug
        difficulty
        topicTags { name }
      }
    }`;

  const res = await fetch("https://leetcode.com/graphql", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, variables: { titleSlug: slug } }),
  });

  if (!res.ok) throw new Error(`GraphQL ${res.status}`);
  const json = await res.json();
  const q = json?.data?.question;
  if (!q) throw new Error("GraphQL returned no question data");

  return {
    // questionFrontendId is the number shown on the site; questionId is internal.
    problem_id: parseInt(q.questionFrontendId || q.questionId, 10),
    title: q.title,
    slug: q.titleSlug || slug,
    difficulty: q.difficulty,
    tags: (q.topicTags || []).map((t) => t.name),
  };
}

/** Runtime/memory render asynchronously after the verdict — poll for them. */
async function fetchSubmissionStats() {
  const stats = {
    runtime_ms: 0,
    memory_mb: 0,
    runtime_percentile: 0,
    memory_percentile: 0,
  };

  const panelText = await waitFor(() => {
    const text = document.body.innerText;
    return /\d+\s*ms/.test(text) && /\bMB\b/.test(text) ? text : null;
  }, 4000);

  if (!panelText) return stats;

  const runtime = panelText.match(/(\d+(?:\.\d+)?)\s*ms/);
  const memory = panelText.match(/(\d+(?:\.\d+)?)\s*MB/);
  const beats = Array.from(panelText.matchAll(/[Bb]eats\s*(\d+(?:\.\d+)?)\s*%/g));

  if (runtime) stats.runtime_ms = Math.round(parseFloat(runtime[1]));
  if (memory) stats.memory_mb = parseFloat(memory[1]);
  if (beats[0]) stats.runtime_percentile = parseFloat(beats[0][1]);
  if (beats[1]) stats.memory_percentile = parseFloat(beats[1][1]);

  return stats;
}

/* ----------------------------------------------------------- payload + post */

async function buildPayload() {
  const slug = currentSlug();
  if (!slug) throw new Error("No problem slug in URL");

  const code = scrapeCode();
  if (!code) throw new Error("Editor was empty — nothing to commit");

  const [meta, stats] = await Promise.all([fetchMetadata(slug), fetchSubmissionStats()]);
  return { ...meta, ...stats, code };
}

async function postToService(payload) {
  const res = await fetch(SERVICE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let body = {};
  try {
    body = await res.json();
  } catch (_) {
    /* non-JSON error body */
  }

  if (!res.ok) throw new Error(body.message || `Service returned ${res.status}`);
  return body;
}

/* ----------------------------------------------------------- toast */

function showToast(state, message) {
  document.querySelectorAll(".lcas-toast").forEach((el) => el.remove());

  const toast = document.createElement("div");
  toast.className = `lcas-toast lcas-toast--${state}`;
  toast.setAttribute("role", "status");
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => toast.remove(), 4000);
}

/* ----------------------------------------------------------- main */

async function sync() {
  if (processed) return;
  processed = true;
  if (observer) observer.disconnect();

  try {
    const payload = await buildPayload();
    const result = await postToService(payload);

    if (result.status === "duplicate") {
      showToast("success", "Already synced");
    } else if (result.message) {
      showToast("success", `Committed — ${result.message}`);
    } else {
      showToast("success", `Committed ${payload.title} to GitHub`);
    }
  } catch (err) {
    console.error("[lc-autosync]", err);
    showToast("fail", `Sync failed: ${err.message}`);
    processed = false; // allow a retry on the next submission
    startObserver();
  }
}

function startObserver() {
  if (observer) observer.disconnect();
  observer = new MutationObserver(() => {
    if (!processed && isAccepted()) sync();
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

/* LeetCode is an SPA: no reload between problems. Reset state on navigation. */
function watchNavigation() {
  let lastPath = window.location.pathname;

  const onNavigate = () => {
    if (window.location.pathname === lastPath) return;
    lastPath = window.location.pathname;
    processed = false;
    startObserver();
  };

  window.addEventListener("popstate", onNavigate);

  // Content scripts run in an isolated world, so patching history.pushState here
  // would never see the page's own calls. Polling the path is the reliable option.
  setInterval(onNavigate, 500);
}

startObserver();
watchNavigation();
