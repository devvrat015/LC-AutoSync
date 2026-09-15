# lc-autosync

Commits your accepted LeetCode solutions to GitHub automatically. A Chrome content
script watches for the "Accepted" verdict, scrapes the code, and POSTs it to a local
FastAPI service, which commits the file and updates the repo's problem table.

```
extension (leetcode.com)  ──POST /submit──>  FastAPI :7337  ──PyGithub──>  GitHub
```

## Layout

```
lc-autosync/
├── service/
│   ├── main.py            FastAPI app: /submit, /health, CORS, duplicate guard
│   ├── schema.py          Pydantic Submission model
│   ├── file_builder.py    repo path + .py file body
│   ├── github_client.py   PyGithub wrapper (cached repo handle)
│   ├── readme_updater.py  upserts the README problem table
│   ├── test_smoke.py      offline test, GitHub stubbed
│   ├── requirements.txt
│   └── .env.example
├── extension/
│   ├── manifest.json
│   ├── content.js
│   └── toast.css
└── start.sh
```

## Setup

**1. Target repo.** Create `leetcode-solutions` on GitHub with a README containing:

```markdown
## Problems

<!-- TABLE_START -->
<!-- TABLE_END -->
```

If the README is missing or has no sentinels, the service adds them on first commit.

**2. Token.** GitHub → Settings → Developer settings → Personal access tokens.
Classic token with `repo` scope, or a fine-grained token with Contents: read/write on
that one repo.

**3. Service.**

```bash
cd service
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # fill in GITHUB_TOKEN and GITHUB_REPO
uvicorn main:app --port 7337 --reload
```

Or `./start.sh` from the project root once the venv exists.

**4. Extension.** `chrome://extensions` → Developer Mode → Load Unpacked →
select `extension/`.

## Testing

Offline, no token needed:

```bash
pip install httpx        # test-only dependency
python test_smoke.py
```

Live, against your real repo:

```bash
curl -X POST http://localhost:7337/submit \
  -H 'Content-Type: application/json' \
  -d '{"problem_id":1,"title":"Two Sum","slug":"two-sum","difficulty":"Easy",
       "tags":["Array","Hash Table"],"runtime_ms":52,"memory_mb":14.3,
       "runtime_percentile":87.5,"memory_percentile":72.1,
       "code":"class Solution:\n    def twoSum(self, nums, target):\n        return []"}'
```

Then solve a real problem on LeetCode and watch for the toast.

## Behaviour notes

- **Output path** is `topics/<first_tag>/NNNN_<slug>.py`, e.g. `topics/array/0001_two_sum.py`.
  The folder comes straight from LeetCode's tag, so it's `array`, not `arrays`.
- **Re-submitting** the same problem overwrites the file and replaces its README row
  rather than appending a second one.
- **Duplicate guard**: the same `problem_id` inside 10 seconds returns
  `{"status": "duplicate"}` with 200, so a double DOM fire doesn't produce two commits.
- **Partial failure**: if the commit succeeds but the README update fails, you still get
  200 with a message — the solution is safely on GitHub. Errors land in
  `service/error.log`.
- **`/submit` is a sync `def`**, so FastAPI runs it in a threadpool and the blocking
  PyGithub calls don't stall the event loop.
