"""FastAPI entry point for lc-autosync.

Run: uvicorn app:app --port 7337 --reload
"""

import time
import traceback
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import github_client
import readme_updater
from schema import Submission, SubmitResponse

app = FastAPI(title="lc-autosync", version="1.0")

# The content script runs on https://leetcode.com and POSTs to http://localhost:7337,
# which is cross-origin. Without this the browser blocks the request.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
      "https://leetcode.com",
      "https://www.leetcode.com",
      "https://lc-auto-sync.vercel.app",
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

import os
ERROR_LOG = Path("/tmp/error.log") if os.getenv("VERCEL") else Path(__file__).parent / "error.log"

# ---------------------------------------------------------------- duplicate guard

_recent: dict[int, float] = {}
DUPLICATE_WINDOW_S = 10


def is_duplicate(problem_id: int) -> bool:
    now = time.time()
    last = _recent.get(problem_id)
    if last is not None and now - last < DUPLICATE_WINDOW_S:
        return True
    _recent[problem_id] = now
    return False


# ---------------------------------------------------------------- error handling


def log_error(context: str, exc: Exception) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    with ERROR_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n[{stamp}] {context}: {exc}\n")
        fh.write(traceback.format_exc())


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Pydantic returns 422 by default; the extension expects 400 + field name."""
    # fields = [".".join(str(p) for p in err["loc"][1:]) for err in exc.errors()]
    print(exc.errors())
    fields = [".".join(str(p) for p in err["loc"][1:]) for err in exc.errors()]
    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": f"invalid or missing field(s): {', '.join(fields)}"},
    )


# ---------------------------------------------------------------- routes


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/submit", response_model=SubmitResponse)
def submit(submission: Submission):
    """Declared `def` on purpose — FastAPI runs it in a threadpool, so the
    blocking PyGithub calls don't stall the event loop."""
    if is_duplicate(submission.problem_id):
        return SubmitResponse(status="duplicate", message="ignored, synced moments ago")

    try:
        url = github_client.commit_solution(submission)
    except Exception as exc:  # noqa: BLE001 — log everything, never crash the service
        log_error(f"commit_solution {submission.slug}", exc)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"commit failed: {exc}"},
        )

    try:
        readme_updater.upsert_row(submission)
    except Exception as exc:  # noqa: BLE001
        # The solution is already on GitHub — a README failure is partial, not fatal.
        log_error(f"upsert_row {submission.slug}", exc)
        return SubmitResponse(status="ok", url=url, message="committed, README update failed")

    return SubmitResponse(status="ok", url=url)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=7337, reload=True)
