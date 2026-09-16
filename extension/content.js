/* LeetCode Auto-Sync — content script
 *
 * Flow: MutationObserver sees "Accepted" -> GraphQL metadata + submission code
 *       -> parse runtime/memory from the result panel -> POST to Vercel service
 */

const SERVICE_URL = "https://lc-auto-sync.vercel.app/submit";

let processed = false;
let observer = null;
let lastNavTime = Date.now();
let lastSyncedCode = "";

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

function graphqlBase() {
  return window.location.origin.includes("leetcode")
    ? window.location.origin
    : "https://leetcode.com";
}

/* ----------------------------------------------------------- detection */

function isAccepted() {
  // Strict only: the submission-result node. A broad "any leaf === Accepted"
  // check fired on stale SPA DOM and submission history.
  const node = document.querySelector('[data-e2e-locator="submission-result"]');
  return !!(node && /accepted/i.test(node.textContent));
}

/* ----------------------------------------------------------- code retrieval
 * Priority: submission API (full file) > scroll-stitched DOM > viewport DOM.
 * Monaco virtualizes/folds lines, so raw `.view-line` reads are partial.
 */

function collectViewportLines(map) {
  document.querySelectorAll(".view-lines .view-line").forEach((el) => {
    const top = parseInt(el.style.top, 10) || 0;
    if (!map.has(top)) {
      map.set(top, el.innerText.replace(/ /g, " ").replace(/\s+$/, ""));
    }
  });
}

/** Scroll the Monaco scroller top-to-bottom, stitching virtualized lines. */
async function scrapeFullViaScroll() {
  const scroller = document.querySelector(
    ".monaco-editor .monaco-scrollable-element"
  );
  if (!scroller) return scrapeViewportCode();
  const map = new Map();
  const prevTop = scroller.scrollTop;
  try {
    scroller.scrollTop = 0;
    await sleep(150);
    collectViewportLines(map);
    const max = scroller.scrollHeight || 2000;
    const step = scroller.clientHeight
      ? Math.max(100, scroller.clientHeight - 50)
      : 200;
    for (let pos = step; pos < max + step; pos += step) {
      scroller.scrollTop = pos;
      await sleep(120);
      const before = map.size;
      collectViewportLines(map);
      if (map.size === before) {
        await sleep(120);
        collectViewportLines(map);
        if (map.size === before) break;
      }
      if (map.size > 500) break; // sanity cap
    }
  } finally {
    scroller.scrollTop = prevTop;
  }
  if (!map.size) return scrapeViewportCode();
  return Array.from(map.entries())
    .sort((a, b) => a[0] - b[0])
    .map((e) => e[1])
    .join("\n")
    .trimEnd();
}

function scrapeViewportCode() {
  const lines = document.querySelectorAll(".view-lines .view-line");
  if (lines.length) {
    return Array.from(lines)
      .map((el) => ({
        top: parseInt(el.style.top, 10) || 0,
        text: el.innerText.replace(/ /g, " ").replace(/\s+$/, ""),
      }))
      .sort((a, b) => a.top - b.top)
      .map((l) => l.text)
      .join("\n")
      .trimEnd();
  }

  const textarea = document.querySelector("textarea.inputarea");
  return textarea ? textarea.value.trimEnd() : "";
}

function findSubmissionId() {
  const m = window.location.pathname.match(/\/submissions\/detail\/(\d+)/);
  if (m) return parseInt(m[1], 10);
  const a = document.querySelector('a[href*="/submissions/detail/"]');
  if (a) {
    const mm = a.getAttribute("href").match(/(\d{6,})/);
    if (mm) return parseInt(mm[1], 10);
  }
  return null;
}

async function fetchCodeViaSubmission(submissionId) {
  const query =
    "query submissionDetails($submissionId: Int!) { submissionDetails(submissionId: $submissionId) { code } }";
  const res = await fetch(graphqlBase() + "/graphql", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, variables: { submissionId } }),
  });
  if (!res.ok) return "";
  const json = await res.json();
  const code = json?.data?.submissionDetails?.code;
  return code ? code.trimEnd() : "";
}

/** Latest accepted submission id for this slug. */
async function fetchLatestAcceptedSubmissionId(slug) {
  const base = graphqlBase();
  const queries = [
    "query subList($questionSlug: String!, $limit: Int!, $offset: Int!) { submissionList(questionSlug: $questionSlug, limit: $limit, offset: $offset) { submissions { id statusDisplay } } }",
    "query subList($questionSlug: String!) { questionSubmissionList(questionSlug: $questionSlug, limit: 20) { submissions { id statusDisplay } } }",
  ];
  for (const query of queries) {
    try {
      const res = await fetch(base + "/graphql", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          variables: { questionSlug: slug, limit: 20, offset: 0 },
        }),
      });
      if (!res.ok) continue;
      const json = await res.json();
      const list =
        json?.data?.submissionList || json?.data?.questionSubmissionList;
      const subs = list?.submissions || [];
      const acc = subs.find((s) => s.statusDisplay === "Accepted");
      if (acc) return parseInt(acc.id, 10);
    } catch (_) {
      /* try next query shape */
    }
  }
  return null;
}

async function getFullCode(slug) {
  try {
    const sid = await fetchLatestAcceptedSubmissionId(slug);
    if (sid) {
      const viaApi = await fetchCodeViaSubmission(sid);
      if (viaApi && viaApi.split("\n").length >= 3) return viaApi;
    }
  } catch (_) {
    /* fall through to DOM */
  }
  const sidDom = findSubmissionId();
  if (sidDom) {
    try {
      const viaApi = await fetchCodeViaSubmission(sidDom);
      if (viaApi && viaApi.split("\n").length >= 3) return viaApi;
    } catch (_) {
      /* fall through */
    }
  }
  try {
    const stitched = await scrapeFullViaScroll();
    if (stitched) return stitched;
  } catch (_) {
    /* fall through */
  }
  return scrapeViewportCode();
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

  const res = await fetch(graphqlBase() + "/graphql", {
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

async function buildPayload(expectedSlug) {
  const slug = currentSlug();
  if (!slug) throw new Error("No problem slug in URL");
  if (expectedSlug && slug !== expectedSlug) throw new Error("Navigated mid-sync, aborted");

  // Give LeetCode a moment to index the new submission.
  await sleep(2000);
  const code = await getFullCode(slug);
  if (!code) throw new Error("Editor was empty — nothing to commit");
  if (code === lastSyncedCode) throw new Error("Same code already synced, aborted");

  const [meta, stats] = await Promise.all([fetchMetadata(slug), fetchSubmissionStats()]);
  if (slug !== currentSlug()) throw new Error("Navigated mid-sync, aborted");
  if (!stats.runtime_ms && !stats.memory_mb) throw new Error("Result stats not ready, aborted");
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
  // SPA navigation leaves stale DOM for a moment. Delay, don't drop.
  if (Date.now() - lastNavTime < 3000) {
    setTimeout(() => {
      if (!processed && isAccepted()) sync();
    }, 3000);
    return;
  }
  const slugAtTrigger = currentSlug();
  processed = true;
  if (observer) observer.disconnect();

  try {
    const payload = await buildPayload(slugAtTrigger);
    const result = await postToService(payload);
    lastSyncedCode = payload.code;

    if (result.status === "duplicate") {
      showToast("success", "Already synced");
    } else if (result.message) {
      showToast("success", `Committed — ${result.message}`);
    } else {
      showToast("success", `Committed ${payload.title} to GitHub`);
    }
    // Re-arm for resubmits on the same page: wait until the verdict clears
    // (user edits / new run), then allow the next Accepted to trigger again.
    // Without this, processed stays true and the 2nd submit is silent.
    (async () => {
      await waitFor(() => !isAccepted(), 60000, 500);
      processed = false;
      startObserver();
    })();
  } catch (err) {
    console.error("[lc-autosync]", err);
    if (/navigated mid-sync/i.test(err.message)) {
      processed = false;
      startObserver();
      return;
    }
    if (/same code already synced/i.test(err.message)) {
      showToast("success", "Already synced");
      processed = false;
      startObserver();
      return;
    }
    showToast("fail", `Sync failed: ${err.message}`);
    processed = false;
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
    lastNavTime = Date.now();
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
