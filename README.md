# LC AutoSync

Automatically sync accepted LeetCode solutions to GitHub.

LC AutoSync is a Chrome extension + FastAPI service that removes the repetitive work of manually copying accepted LeetCode solutions into a GitHub repository. When a submission is accepted, the extension captures the solution code and submission metadata, sends it to a local FastAPI service, and the service commits the solution and updates the repository's problem table.

## How It Works

```text
LeetCode
   │
   │ Accepted
   ▼
Chrome Extension
   │
   │ POST /submit
   ▼
FastAPI Service :7337
   │
   │ PyGithub
   ▼
GitHub Repository
   ├── Solution file
   └── README problem table
```

## Features

- Automatically detects accepted LeetCode submissions
- Captures submitted solution code and problem metadata
- Records difficulty, tags, runtime, memory, and percentile statistics
- Validates submissions before processing
- Creates or updates solution files in GitHub
- Organizes solutions by LeetCode's first tag
- Automatically maintains the repository README problem table
- Prevents duplicate commits from repeated submission events
- Handles partial failures without losing a successfully committed solution
- Logs service errors locally
- Provides a health-check endpoint
- Includes an offline smoke test with GitHub operations stubbed

## Repository Output

Solutions are stored using the first LeetCode tag and a zero-padded problem ID:

```text
topics/<first_tag>/NNNN_<slug>.py
```

For example:

```text
topics/
└── array/
    └── 0001_two_sum.py
```

A generated solution file contains the submission metadata followed by the submitted code.

The README problem table is updated along with the solution.

## Project Structure

```text
lc-autosync/
├── service/
│   ├── main.py            FastAPI app: /submit, /health, CORS, duplicate guard
│   ├── schema.py          Pydantic submission models
│   ├── file_builder.py    Repository path and solution file generation
│   ├── github_client.py   PyGithub integration
│   ├── readme_updater.py  README problem-table synchronization
│   ├── test_smoke.py      Offline smoke test with GitHub stubbed
│   ├── requirements.txt
│   └── .env
│
├── extension/
│   ├── manifest.json      Chrome extension configuration
│   ├── content.js         LeetCode detection and submission extraction
│   └── toast.css          Sync status notifications
│
├── .gitignore
├── README.md
└── start.sh
```

## Tech Stack

| Component | Technology |
|---|---|
| Browser integration | Chrome Extension (Manifest V3) |
| Extension logic | JavaScript |
| Backend | FastAPI |
| Validation | Pydantic |
| GitHub integration | PyGithub |
| Configuration | python-dotenv |
| Repository | GitHub |

## Setup

### 1. Create the Target Repository

Create a GitHub repository for your LeetCode solutions, for example:

```text
leetcode-solutions
```

The service manages the problem table between these markers:

```markdown
## Problems

<!-- TABLE_START -->
<!-- TABLE_END -->
```

If the README does not contain the markers, the service can add them when it first updates the repository.

### 2. Configure GitHub Authentication

Create a GitHub Personal Access Token with permission to read and write repository contents for the target solutions repository.

For a classic token, use the `repo` scope.

For a fine-grained token, grant **Contents: Read and write** access to the target repository.

Create:

```text
service/.env
```

and configure:

```env
GITHUB_TOKEN=your_github_token
GITHUB_REPO=your_username/leetcode-solutions
```

Keep the real `.env` file private. The repository should contain only `.env.example`.

### 3. Install the FastAPI Service

From the `service` directory:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start the service:

```powershell
uvicorn main:app --port 7337 --reload
```

The API will run at:

```text
http://localhost:7337
```

You can also start it using:

```bash
./start.sh
```

once the virtual environment is configured.

### 4. Verify the Service

Open:

```text
http://localhost:7337/health
```

Expected response:

```json
{
  "status": "ok"
}
```

### 5. Install the Chrome Extension

1. Open Chrome.
2. Navigate to `chrome://extensions`.
3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select the project's `extension/` directory.

## Usage

Once the service is running and the extension is loaded:

1. Open a LeetCode problem.
2. Submit your solution.
3. When the submission is accepted, LC AutoSync detects the result.
4. The extension collects the solution and submission information.
5. The extension sends the data to the local FastAPI service.
6. The service creates or updates the solution in GitHub.
7. The README problem table is synchronized.
8. A toast notification reports the sync result.

This turns the normal workflow:

```text
Solve → Copy → Create file → Add metadata → Commit → Update README
```

into:

```text
Solve → Submit → Accepted → Automatically synced
```

## API

### `GET /health`

Checks whether the local service is running.

Response:

```json
{
  "status": "ok"
}
```

### `POST /submit`

Receives an accepted LeetCode submission.

Example request:

```json
{
  "problem_id": 1,
  "title": "Two Sum",
  "slug": "two-sum",
  "difficulty": "Easy",
  "tags": ["Array", "Hash Table"],
  "runtime_ms": 52,
  "memory_mb": 14.3,
  "runtime_percentile": 87.5,
  "memory_percentile": 72.1,
  "code": "class Solution:\n    def twoSum(self, nums, target):\n        return []"
}
```

Successful response:

```json
{
  "status": "ok",
  "url": "https://github.com/..."
}
```

If the same problem is received inside the duplicate window:

```json
{
  "status": "duplicate",
  "message": "ignored, synced moments ago"
}
```

## Behaviour Notes

### Solution Organization

The output path is:

```text
topics/<first_tag>/NNNN_<slug>.py
```

The folder is derived directly from LeetCode's first tag. For example, `Array` becomes:

```text
topics/array/
```

### Re-submissions

Submitting the same problem again updates the existing solution file and replaces its README row rather than creating a duplicate entry.

### Duplicate Guard

The service keeps a short in-memory record of recently processed problem IDs.

If the same `problem_id` is received within **10 seconds**, the request returns:

```json
{
  "status": "duplicate"
}
```

This prevents repeated browser events from producing multiple GitHub commits.

### Partial Failures

The solution commit and README update are handled separately.

If the solution is successfully committed but the README update fails, the solution remains safely stored on GitHub. The service returns a successful response with a message describing the README failure, and the error is written to:

```text
service/error.log
```

### Request Handling

The `/submit` endpoint is implemented as a synchronous FastAPI handler because the GitHub integration uses blocking PyGithub operations. FastAPI can execute the handler in its threadpool so those operations do not block the asynchronous event loop.

## Testing

### Offline Smoke Test

The project includes an offline smoke test that does not require a GitHub token or live GitHub access.

From the `service` directory:

```powershell
pip install httpx
python test_smoke.py
```

The smoke test verifies core service behaviour including:

- solution path generation
- solution file generation
- successful submission handling
- duplicate detection
- request validation
- README row insertion
- README row replacement
- README table sorting
- preservation of content outside the managed table

### Live API Test

You can also test the service directly against your configured GitHub repository.

On PowerShell:

```powershell
$body = @{
    problem_id = 1
    title = "Two Sum"
    slug = "two-sum"
    difficulty = "Easy"
    tags = @("Array", "Hash Table")
    runtime_ms = 52
    memory_mb = 14.3
    runtime_percentile = 87.5
    memory_percentile = 72.1
    code = "class Solution:`n    def twoSum(self, nums, target):`n        return []"
} | ConvertTo-Json -Compress

Invoke-RestMethod `
    -Uri "http://localhost:7337/submit" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body
```

After that, solve a real problem on LeetCode and verify that the solution and README entry appear in the target repository.

## Architecture

LC AutoSync separates browser-side detection from GitHub operations:

```text
┌─────────────────────────┐
│     LeetCode Page       │
│                         │
│  Accepted submission    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│    Chrome Extension     │
│                         │
│  Detect → Extract →     │
│  Build submission       │
└────────────┬────────────┘
             │ HTTP
             │ POST /submit
             ▼
┌─────────────────────────┐
│      FastAPI Service    │
│         :7337            │
│                         │
│ Validate → Deduplicate  │
│ → Commit → Update       │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│       GitHub API        │
│                         │
│ Solution + README       │
└─────────────────────────┘
```

Keeping GitHub operations in the local Python service also means the GitHub token does not need to be embedded in the Chrome extension's client-side JavaScript.

## Design Details

### README Table Management

Only the section between:

```markdown
<!-- TABLE_START -->
<!-- TABLE_END -->
```

is managed automatically. This allows the rest of the README to remain under normal project documentation control.

### GitHub Integration

The service uses PyGithub to interact with the target repository. Solution files are created when needed and updated on subsequent submissions.

### Configuration and Secrets

GitHub credentials are loaded from environment variables rather than being hard-coded in source files. The real `.env` file is excluded from Git through `.gitignore`.

## Future Improvements

Potential improvements include:

- extension settings for configuring the target repository
- richer submission history
- configurable solution organization
- expanded automated test coverage
- more detailed sync status and diagnostics
- optional remote deployment of the service

## License

This project is currently intended as a personal learning and automation project. Add a license if you plan to distribute or reuse it publicly.
