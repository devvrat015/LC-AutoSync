# LC AutoSync — Project Overview (Interview Guide)

> **Note:** written against the original single-user deployment. Since then:
> auth is per-user GitHub OAuth (no `GITHUB_TOKEN`/`GITHUB_REPO` on the
> server), dedup is keyed by GitHub user id + repo + branch + problem + code
> hash (not bare `problem_id`), and output extensions follow the submission
> language. See `README.md` for the shipping behavior.

## 1. One-paragraph pitch

LC AutoSync removes the manual work of saving LeetCode solutions to GitHub.
A Chrome extension (Manifest V3) detects an **Accepted** verdict, fetches the
problem metadata + exact submitted code via LeetCode's GraphQL API, and POSTs it
to a FastAPI service on Vercel. The service validates with Pydantic, commits the
solution file via PyGithub, and updates a problem table in the solutions repo's
README. Workflow goes from
`Solve → Copy → Create file → Commit → Update README` to
`Solve → Submit → Accepted → Automatically synced`.

## 2. End-to-end workflow

```text
LeetCode problem page
  │ user submits, verdict = Accepted
  ▼
extension/content.js (isolated content script)
  │ 1. MutationObserver sees [data-e2e-locator="submission-result"] = Accepted
  │ 2. sleep 2s (let LeetCode index the submission)
  │ 3. GraphQL: question metadata + submissionList → submissionDetails(code)
  │ 4. scrape result panel: runtime ms/MB + beats %
  │ 5. POST {problem_id, title, slug, difficulty, tags, runtime_*, memory_*, code}
  ▼
https://lc-auto-sync.vercel.app/submit  (FastAPI, service/main.py)
  │ 1. Pydantic validation (400 + field names on failure)
  │ 2. duplicate guard (10s per problem_id → {"status":"duplicate"})
  │ 3. github_client.commit_solution() → solution file URL
  │ 4. readme_updater.upsert_row() → README table replace-or-insert
  ▼
github.com/devvrat015/leetcode-solutions
  ├── topics/<first_tag>/NNNN_<slug>.py   (e.g. topics/array/0001_two_sum.py)
  └── README.md problem table (managed block only)
```

Toast (`toast.css` + `showToast`) reports each outcome on the LeetCode page:
`Committed <title>`, `Already synced`, or `Sync failed: <reason>`.

## 3. File-by-file responsibility

| File | Responsibility |
|---|---|
| `extension/manifest.json` | MV3 config. `content_scripts` injects `content.js`+`toast.css` on `leetcode.com` + `www.leetcode.com` problem pages. `host_permissions` allow LeetCode GraphQL + the Vercel domain. No secrets here. |
| `extension/content.js` | All browser logic: Accept detection, GraphQL fetch, stats parse, POST, toast, SPA-navigation handling, resubmit re-arm. No GitHub token — it never talks to GitHub directly. |
| `extension/toast.css` | Bottom-right success/fail toast styling. One element, auto-removed after 4s. |
| `service/main.py` | FastAPI app (`app`). Routes `GET /health`, `POST /submit`. CORS for LeetCode origins. Pydantic-422 → 400 mapper. In-memory 10s duplicate guard. `/tmp/error.log` on Vercel, local `error.log` otherwise. Sync `def` handler so blocking PyGithub runs in FastAPI's threadpool. |
| `service/schema.py` | `Submission` (input) + `SubmitResponse` (output) Pydantic models. `padded_id` (`1` → `0001`), `url` (canonical problem link). Validation happens at the FastAPI boundary. |
| `service/file_builder.py` | Pure functions, no I/O. `resolve_path` → `topics/<first_tag>/NNNN_<slug>.py` (slugified). `build_content` → docstring header (id, link, difficulty, tags, runtime/memory) + code. `commit_message` → `feat: add ...` / update variant. |
| `service/github_client.py` | PyGithub wrapper. `get_repo()` reads `GITHUB_TOKEN`/`GITHUB_REPO` env (cached). `commit_solution()` creates or updates the file, returns its `html_url`. Blocking I/O by design. |
| `service/readme_updater.py` | README table sync. Only touches the block between `<!-- TABLE_START -->` / `<!-- TABLE_END -->`, preserves everything else byte-for-byte. `upsert_row` replaces the row for the same problem id, sorts ascending, skips empty commits. Seeds a README if missing. |
| `service/test_smoke.py` | Offline test with GitHub stubbed (`fake_commit`/`fake_upsert`). Covers path generation, `/submit` 200, duplicate guard, 400 validation, row insert/replace/sort, content preservation. Run: `python test_smoke.py` (needs `httpx`). |
| `api/index.py` | Vercel serverless entry. Adds `service/` to `sys.path`, re-exports `app` from `main`. Lets the whole FastAPI app run as one Vercel function. |
| `vercel.json` | `rewrites: /(.*) → /api/index` so `/health` and `/submit` resolve on the production domain. |
| `requirements.txt` | `fastapi, uvicorn[standard], pydantic, python-dotenv, PyGithub` (root, read by Vercel). |
| `start.sh` | Local runner (`uvicorn main:app --host 127.0.0.1 --port 7337`). Vercel ignores it. |
| `.gitignore` | Excludes `.env`, `venv/`, logs, caches. Secrets never committed; Vercel env vars supply them in prod. |

## 4. Key design decisions (say these in the interview)

1. **Token never touches the browser.** The extension sends only solution data;
   the GitHub token lives in backend env vars. Embedding it in extension JS
   would leak it to anyone installing the extension.
2. **Authoritative code via submission API, not DOM scraping.** Monaco
   virtualizes (only the viewport is in the DOM) and folding removes lines, so
   `.view-line` reads truncate. `submissionList → submissionDetails(code)`
   returns the exact submitted file. Scroll-stitching the editor is fallback only.
3. **Strict Accepted detection.** The first version matched any leaf node with
   text `Accepted` and auto-committed on page open (stale SPA DOM / submission
   history). Now only `[data-e2e-locator="submission-result"]` counts.
4. **SPA-aware observer.** LeetCode doesn't reload between problems. A
   Harlem-shake of `lastNavTime` (3s settle delay), pathname polling, slug
   checks before/after awaits, and verdict-clear re-arm prevent stale commits
   and make resubmits on the same page work.
5. **Two-layer dedup.** Client `lastSyncedCode` + server 10s `problem_id` window
   absorb double-firing MutationObserver events. Resubmits after expiry are
   treated as updates (replace file + row, never duplicate).
6. **Sync `def`, not `async def`, for `/submit`.** PyGithub is blocking; a sync
   handler lets FastAPI run it in the threadpool without stalling the event loop.
7. **Partial-failure tolerance.** Solution commit and README update are separate
   try blocks. If the README fails after a good commit, the API still returns
   `ok` with `message: "committed, README update failed"` and logs the error —
   the solution is never lost to a docs failure.
8. **Surgical README edits.** Only the `TABLE_START/END` block is rewritten;
   prose above/below is preserved, rows keyed by problem id, sorted ascending.
9. **Serverless trade-offs accepted.** On Vercel there is no persistent disk
   (`/tmp` log only) and in-memory dedup is per-instance (cold starts reset it).
   Harmless here: worst case is an extra update commit, never data loss.
10. **Validation errors shaped for the UI.** Pydantic 422s are remapped to
    `400 {"status":"error","message":"invalid or missing field(s): code"}` so
    the toast can show the field name.

## 5. API contract

`GET /health` → `{"status":"ok"}`

`POST /submit` request:
```json
{
  "problem_id": 1, "title": "Two Sum", "slug": "two-sum",
  "difficulty": "Easy", "tags": ["Array", "Hash Table"],
  "runtime_ms": 52, "memory_mb": 14.3,
  "runtime_percentile": 87.5, "memory_percentile": 72.1,
  "code": "class Solution:\n ..."
}
```
Responses: `{"status":"ok","url":"https://github.com/..."}` |
`{"status":"duplicate","message":"ignored, synced moments ago"}` |
`{"status":"error","message":"..."}` (400 validation, 500 commit failure).

## 6. Testing & deployment

- **Offline:** `service/venv` active → `python test_smoke.py` (no token needed).
- **Live:** PowerShell `Invoke-RestMethod` against
  `https://lc-auto-sync.vercel.app/submit`, then check the solutions repo.
- **Deploy:** push to GitHub → Vercel auto-deploys (`api/index.py` +
  `vercel.json`). Env vars `GITHUB_TOKEN` (`repo` scope) and `GITHUB_REPO` set
  in Vercel Dashboard → Redeploy. Extension points at the prod URL; reload it
  in `chrome://extensions` after any `content.js`/`manifest.json` edit
  (unpacked extensions read from disk — no commit needed to test locally).

## 7. Failure modes (memorize 4)

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to fetch` at `fetchMetadata` | on `www` host without permission | `host_permissions` + `matches` cover both hosts |
| Commit on page open, wrong code | broad Accepted match + stale SPA DOM | strict selector + 3s nav delay + stats-ready check |
| Truncated file (top/bottom missing) | viewport-only Monaco read / folded lines | submission-details API; scroll-stitch fallback |
| No toast on resubmit | observer disconnected after first success | re-arm after verdict clears; `Already synced` for identical code |

## 8. 60-second interview script

> "I built LC AutoSync because I was tired of copy-pasting LeetCode solutions
> into GitHub. A Manifest V3 content script watches for the Accepted verdict —
> strictly the submission-result node, since a broad matcher caused false
> positives on LeetCode's SPA navigation. It fetches question metadata and the
> exact submitted code through LeetCode's GraphQL API — I learned the hard way
> that scraping Monaco's DOM truncates files because of virtualization and
> folding — then POSTs to a FastAPI service I deployed on Vercel. The service
> validates with Pydantic, dedups rapid double-events, commits via PyGithub to
> a tag-organized path, and surgically updates just the README table block.
> Solution and docs updates are independent so a README failure never loses a
> commit. The GitHub token stays server-side; the extension holds no secrets."

## 9. Likely follow-up questions

- *Why not put the token in the extension and call GitHub directly?* → leaks
  the token to every install; backend keeps it in env vars.
- *Why sync `def` handler?* → PyGithub blocks; FastAPI threadpools it so the
  event loop stays free.
- *How do resubmits behave?* → update file + replace README row; rapid repeats
  return `duplicate` / `Already synced`.
- *Vercel limits?* → read-only disk (`/tmp` logs), stateless dedup, ~10s
  timeout — all acceptable; worst case is a redundant update commit.
- *What would you add next?* → per-user settings page, full Monaco MAIN-world
  reader via `chrome.scripting`, pytest suite replacing the script smoke test,
  retry queue for offline submits.
