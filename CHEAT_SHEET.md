# LC AutoSync — 1-Page Cheat Sheet

**Pitch:** Chrome extension detects Accepted → POSTs to FastAPI on Vercel →
commits solution + updates README table. `Solve → Submit → Auto-synced`.

**Flow:** LeetCode → `content.js` (Accept detect, GraphQL meta + code, stats,
POST) → `POST /submit` (`main.py`: validate → dedup → commit → README) →
`topics/<tag>/NNNN_<slug>.py` + README `TABLE_START/END` block → toast.

**Files:** `manifest.json` (MV3 inject + perms, no secrets) · `content.js`
(browser logic only) · `toast.css` (4s toast) · `main.py` (`/health`,
`/submit`, CORS, 400 mapper, 10s dedup, `/tmp` log, sync `def`→threadpool) ·
`schema.py` (validate + `padded_id`/`url`) · `file_builder.py` (path/header,
no I/O) · `github_client.py` (env token, create-or-update) ·
`readme_updater.py` (replace-or-insert row, sort, preserve rest) ·
`test_smoke.py` (offline stubs) · `api/index.py` (Vercel entry) ·
`vercel.json` (rewrite to `/api/index`).

**5 decisions to say:** (1) token server-side only; (2) code via
`submissionList→submissionDetails`, DOM truncates (virtualize/fold);
(3) strict Accepted selector (broad match false-fired on SPA DOM);
(4) sync `def` for blocking PyGithub; (5) solution+README independent —
README fail never loses commit.

**API:** `GET /health`→`{ok}`. `POST /submit`→`{ok,url}` |
`{duplicate}` (same user + same repo/branch/problem/code within 10s) |
`{error}` (400 field names, mapped 401/403/404/409/429, generic 500).

**Resubmit:** update file + replace row, never duplicate. Same-code fast
repeat → `Already synced` / `duplicate`; different code → update commits.
Different users never share dedup state (key includes GitHub user id).

**Vercel limits:** no disk (`/tmp`), stateless dedup, ~10s timeout. Worst case:
redundant update commit.

**4 bugs fixed:** page-open commit (strict selector + 3s nav delay) ·
truncated file (submission API) · no resubmit toast (re-arm after verdict
clears) · `www` fetch fail (both hosts in manifest).

**60s script:** "Extension watches the verdict node, fetches metadata and
exact submitted code via GraphQL, POSTs to FastAPI on Vercel; service
validates, dedups, commits tag-organized file, updates only the README table
block. Token stays server-side; docs failure never loses a solution."
