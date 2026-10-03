"""FastAPI entry point for lc-autosync.

Run: uvicorn app:app --port 7337 --reload
"""

import os
import time
import traceback
import hashlib
import httpx
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from github import Github

import github_client
import readme_updater
from schema import Submission, SubmitResponse, CodeExchangeRequest, GitHubUser, RepoInfo, BranchInfo

app = FastAPI(title="lc-autosync", version="2.0")

ENV = os.getenv("ENV", "dev").lower()
IS_PROD = ENV == "production" or bool(os.getenv("VERCEL"))

# Production: only the web-store extension + LeetCode pages. Development
# additionally allows a local service URL for testing.
# The backend holds no cookies/sessions so a malicious site cannot ride
# ambient auth — every request needs an explicit Bearer token that only the
# user's own extension holds. The extension origin is therefore a
# defense-in-depth layer, not the security boundary.
# Post-publish: set LC_EXTENSION_ID (Vercel env) to the Chrome Web Store
# extension ID to pin production CORS to exactly:
#   chrome-extension://<PRODUCTION_EXTENSION_ID>
# Until then (ID unknown), production allows any chrome-extension:// origin.
_PROD_EXTENSION_ID = os.getenv("LC_EXTENSION_ID", "").strip()
_chrome_origin = (
    f"chrome-extension://{_PROD_EXTENSION_ID}"
    if _PROD_EXTENSION_ID
    else r"chrome-extension://.*"
)
ALLOWED_ORIGIN_REGEX = (
    rf"https://.*leetcode\.com|https://lc-auto-sync\.vercel\.app|{_chrome_origin}"
    if IS_PROD
    else r"https://.*leetcode\.com|https://lc-auto-sync\.vercel\.app|chrome-extension://.*|http://(localhost|127\.0\.0\.1)(:\d+)?"
)
# The content script runs on https://leetcode.com and POSTs to the service,
# which is cross-origin. Without this the browser blocks the request.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

from dotenv import load_dotenv

load_dotenv()

ERROR_LOG = Path("/tmp/error.log") if os.getenv("VERCEL") else Path(__file__).parent / "error.log"

# ---------------------------------------------------------------- duplicate guard
# Stable sync identity: authenticated GitHub user id + selected repository +
# branch + problem + code hash. The user id comes from GitHub (get_user().id),
# NOT from the OAuth token: tokens rotate on reconnect, and a credential must
# never double as an identity. Two users syncing identical code to the same
# repo never collide; the same user re-sending the same code within the window
# is a duplicate; different code is an update, not a duplicate.
# Instance-local like the rate limiter below: a serverless restart clears it,
# so worst case is one redundant update commit, never data loss.
_recent: dict[str, float] = {}
DUPLICATE_WINDOW_S = 10
_MAX_RECENT_KEYS = 5000


def sync_identity_key(user_id: int, repo_full_name: str, branch: str, problem_id: int, code: str) -> str:
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
    raw = f"{user_id}|{repo_full_name.lower()}|{branch}|{problem_id}|{code_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_duplicate(user_id: int, repo_full_name: str, branch: str, problem_id: int, code: str) -> bool:
    now = time.time()
    key = sync_identity_key(user_id, repo_full_name, branch, problem_id, code)
    # Prune expired entries; cap size so the dict cannot grow unbounded.
    expired = [k for k, ts in _recent.items() if now - ts >= DUPLICATE_WINDOW_S]
    for k in expired:
        del _recent[k]
    if len(_recent) > _MAX_RECENT_KEYS:
        for k in sorted(_recent, key=_recent.get)[: len(_recent) - _MAX_RECENT_KEYS]:
            del _recent[k]
    last = _recent.get(key)
    if last is not None and now - last < DUPLICATE_WINDOW_S:
        return True
    _recent[key] = now
    return False


# ---------------------------------------------------------------- rate limiting
# Lightweight best-effort limiter (in-memory, per instance). On Vercel each
# serverless instance has its own counters, and a restart wipes them — this
# stops accidental loops and casual abuse, not a determined distributed flood.
# No Redis by design. Keys hold only hashes/ids (never tokens), and both the
# key count and per-key hit lists are bounded so memory stays flat.
_rate_hits: dict[str, list[float]] = {}
RATE_LIMITS = {
    "submit": (30, 60.0),      # 30 submits / minute / sync identity
    "exchange": (10, 60.0),    # 10 OAuth exchanges / minute / IP
    "github": (60, 60.0),      # 60 repo listings / minute / token
}
_MAX_RATE_KEYS = 5000
_MAX_WINDOW_S = 60.0


def _is_rate_limited(bucket: str, key: str) -> bool:
    limit, window = RATE_LIMITS[bucket]
    now = time.time()
    hits = _rate_hits.setdefault(f"{bucket}:{key}", [])
    while hits and now - hits[0] >= window:
        hits.pop(0)
    if len(hits) >= limit:
        return True
    hits.append(now)
    if len(_rate_hits) > _MAX_RATE_KEYS:
        # Evict fully-expired keys first, then oldest-first as a backstop.
        expired = [k for k, v in _rate_hits.items() if not v or now - v[-1] >= _MAX_WINDOW_S]
        for k in expired[: len(_rate_hits) - _MAX_RATE_KEYS]:
            del _rate_hits[k]
        if len(_rate_hits) > _MAX_RATE_KEYS:
            oldest = sorted(_rate_hits, key=lambda k: _rate_hits[k][0] if _rate_hits[k] else now)
            for k in oldest[: len(_rate_hits) - _MAX_RATE_KEYS]:
                del _rate_hits[k]
    return False


# ---------------------------------------------------------------- error handling


def log_error(context: str, exc: Exception) -> None:
    # Never log tokens, codes, or full payloads — only stable identifiers.
    stamp = datetime.now().isoformat(timespec="seconds")
    with ERROR_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n[{stamp}] {context}: {type(exc).__name__}: {exc}\n")
        fh.write(traceback.format_exc(limit=5))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Pydantic returns 422 by default; the extension expects 400 + field name."""
    fields = [".".join(str(p) for p in err["loc"][1:]) for err in exc.errors()]
    # Log field names only — never input values (they contain solution code).
    print(f"validation failed: {fields}")
    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": f"invalid or missing field(s): {', '.join(fields)}"},
    )


# ---------------------------------------------------------------- helpers

def extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "GitHub token required. Connect GitHub in the extension popup."}
        )
    token = auth[len("Bearer "):].strip()
    if not token or len(token) > 256:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "GitHub token required. Connect GitHub in the extension popup."}
        )
    return token


def _token_fingerprint(token: str) -> str:
    """Short non-reversible fingerprint for rate-limit keys and logs."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


# Cache of token-fingerprint -> (github user id, resolved_at). Stores only the
# numeric user id, never the token. Bounded + TTL so memory stays flat and a
# revoked/reissued token re-resolves within minutes.
_identity_cache: dict[str, tuple[int, float]] = {}
_IDENTITY_TTL_S = 300
_MAX_IDENTITY_KEYS = 5000


def get_caller_identity(token: str) -> int:
    """Stable authenticated GitHub user id for this token. Raises on bad token."""
    fp = _token_fingerprint(token)
    now = time.time()
    hit = _identity_cache.get(fp)
    if hit is not None and now - hit[1] < _IDENTITY_TTL_S:
        return hit[0]
    user_id = Github(token).get_user().id
    if len(_identity_cache) >= _MAX_IDENTITY_KEYS:
        oldest = sorted(_identity_cache, key=lambda k: _identity_cache[k][1])[: len(_identity_cache) - _MAX_IDENTITY_KEYS + 1]
        for k in oldest:
            del _identity_cache[k]
    _identity_cache[fp] = (user_id, now)
    return user_id


def github_error_response(context: str, exc: Exception):
    """Map PyGithub failures to user-facing status codes without leaking internals."""
    status = getattr(exc, "status", None)
    msg = str(getattr(exc, "data", "") or exc)
    lowered = f"{msg}".lower()
    if status == 401 or "bad credentials" in lowered:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "GitHub authorization expired. Reconnect GitHub in the extension popup."},
        )
    if status == 403 and ("rate limit" in lowered or "abuse" in lowered):
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "GitHub rate limit reached. Wait a minute and try again."},
        )
    if status == 403:
        return JSONResponse(
            status_code=403,
            content={"status": "error", "message": "GitHub refused the operation. Check repository and branch permissions."},
        )
    if status == 404:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Repository or branch not found. Check your extension settings."},
        )
    if status in (409, 422):
        return JSONResponse(
            status_code=409,
            content={"status": "error", "message": "GitHub reported a conflict. Try syncing again."},
        )
    log_error(context, exc)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Sync failed. Try again later."},
    )


# ---------------------------------------------------------------- routes


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/github/exchange")
async def github_exchange(req: CodeExchangeRequest, request: Request):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "OAuth is not configured on the server."},
        )
    caller = request.client.host if request.client else "unknown"
    if _is_rate_limited("exchange", caller):
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "Too many authorization attempts. Wait a minute and try again."},
        )
    try:
        exchange_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": req.code,
        }
        # Same redirect URI as the authorize request (GitHub requires them to
        # match when one was used). Supplied by the extension per session.
        if req.redirect_uri:
            exchange_data["redirect_uri"] = req.redirect_uri
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                data=exchange_data,
                headers={"Accept": "application/json"}
            )
    except httpx.HTTPError as exc:
        log_error("github_exchange network", exc)
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "GitHub authorization failed. Try again."},
        )
    try:
        body = resp.json()
    except Exception:
        body = {}
    # Never log or return the raw exchange payload beyond the token itself;
    # the authorization code is single-use and must not be retained.
    if resp.status_code != 200 or not isinstance(body, dict) or "error" in body or "access_token" not in body:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "GitHub authorization failed. Try connecting again."},
        )
    return {"access_token": body["access_token"], "token_type": "bearer", "scope": body.get("scope", "")}

@app.get("/github/user", response_model=GitHubUser)
async def get_github_user(request: Request):
    try:
        token = extract_token(request)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=e.detail)
    if _is_rate_limited("github", _token_fingerprint(token)):
        return JSONResponse(status_code=429, content={"status": "error", "message": "Too many requests. Slow down and try again."})
    try:
        gh = Github(token)
        user = gh.get_user()
        return GitHubUser(login=user.login, name=user.name, avatar_url=user.avatar_url)
    except Exception as exc:  # noqa: BLE001
        return github_error_response("github_user", exc)

@app.get("/github/repos", response_model=list[RepoInfo])
async def get_github_repos(request: Request):
    try:
        token = extract_token(request)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=e.detail)
    if _is_rate_limited("github", _token_fingerprint(token)):
        return JSONResponse(status_code=429, content={"status": "error", "message": "Too many requests. Slow down and try again."})
    try:
        gh = Github(token)
        user = gh.get_user()
        repos = user.get_repos(sort='updated')
        res = []
        for r in repos:
            if r.permissions and r.permissions.push:
                res.append(RepoInfo(full_name=r.full_name, name=r.name, private=r.private, default_branch=r.default_branch))
        return res
    except Exception as exc:  # noqa: BLE001
        return github_error_response("github_repos", exc)

@app.get("/github/repos/{owner}/{repo}/branches", response_model=list[BranchInfo])
async def get_github_branches(request: Request, owner: str, repo: str):
    import re as _re
    if not _re.match(r"^[A-Za-z0-9_.-]+$", owner) or not _re.match(r"^[A-Za-z0-9_.-]+$", repo):
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid repository reference."})
    try:
        token = extract_token(request)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=e.detail)
    if _is_rate_limited("github", _token_fingerprint(token)):
        return JSONResponse(status_code=429, content={"status": "error", "message": "Too many requests. Slow down and try again."})
    try:
        gh = Github(token)
        repository = gh.get_repo(f"{owner}/{repo}")
        return [BranchInfo(name=b.name) for b in repository.get_branches()]
    except Exception as exc:  # noqa: BLE001
        return github_error_response("github_branches", exc)


@app.post("/submit", response_model=SubmitResponse)
def submit(request: Request, submission: Submission):
    """Declared `def` on purpose — FastAPI runs it in a threadpool, so the
    blocking PyGithub calls don't stall the event loop."""
    try:
        token = extract_token(request)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=e.detail)

    repo_full_name = f"{submission.repo_owner}/{submission.repo_name}"
    branch = submission.branch

    # Stable caller identity first: every downstream key (dedup, rate limit)
    # is scoped to this user id, so User A can never affect User B's state.
    try:
        user_id = get_caller_identity(token)
    except Exception as exc:  # noqa: BLE001 — bad/expired token
        return github_error_response(f"identity {repo_full_name}#{submission.problem_id}", exc)

    if _is_rate_limited("submit", sync_identity_key(user_id, repo_full_name, branch, submission.problem_id, submission.code)):
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "Too many syncs. Slow down and try again."},
        )
    # Second bucket per token so rotating code cannot bypass the limiter.
    if _is_rate_limited("submit", f"tok:{_token_fingerprint(token)}"):
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "Too many syncs. Slow down and try again."},
        )

    if is_duplicate(user_id, repo_full_name, branch, submission.problem_id, submission.code):
        return SubmitResponse(status="duplicate", message="ignored, synced moments ago")

    # Verify the caller's token actually has push access to this repo+branch
    # before attempting any write. GitHub is the source of truth.
    try:
        github_client.verify_write_access(token, repo_full_name, branch)
    except Exception as exc:  # noqa: BLE001 — mapped, never crashes the service
        return github_error_response(f"verify_access {repo_full_name}#{submission.problem_id}", exc)

    try:
        url = github_client.commit_solution(token, repo_full_name, branch, submission)
    except Exception as exc:  # noqa: BLE001 — mapped, never crashes the service
        return github_error_response(f"commit_solution {repo_full_name}#{submission.problem_id}", exc)

    try:
        readme_updater.upsert_row(token, repo_full_name, branch, submission)
    except Exception as exc:  # noqa: BLE001
        # The solution is already on GitHub — a README failure is partial, not fatal.
        log_error(f"upsert_row {repo_full_name}#{submission.problem_id}", exc)
        return SubmitResponse(status="ok", url=url, message="committed, README update failed")

    return SubmitResponse(status="ok", url=url)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=7337, reload=True)
