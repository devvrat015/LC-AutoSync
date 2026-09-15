"""Thin wrapper around PyGithub.

Everything here is blocking network I/O. FastAPI runs the /submit handler in a
threadpool (it's declared `def`, not `async def`), so these calls don't block
the event loop.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from github import Github, GithubException
from github.Repository import Repository

import file_builder
from schema import Submission

load_dotenv()


@lru_cache(maxsize=1)
def get_repo() -> Repository:
    token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("GITHUB_REPO")
    if not token or not repo_name:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPO must be set in service/.env")
    return Github(token).get_repo(repo_name)


def _get_sha(repo: Repository, path: str) -> str | None:
    """Current blob SHA, or None if the file doesn't exist yet."""
    try:
        contents = repo.get_contents(path)
        if isinstance(contents, list):  # path is a directory
            return None
        return contents.sha
    except GithubException as exc:
        if exc.status == 404:
            return None
        raise


def commit_solution(submission: Submission) -> str:
    """Create or update the solution file. Returns its GitHub URL."""
    repo = get_repo()
    path = file_builder.resolve_path(submission)
    content = file_builder.build_content(submission)
    message = file_builder.commit_message(submission)

    sha = _get_sha(repo, path)
    if sha:
        update_msg = (
            f"chore: update {submission.padded_id}. {submission.title} "
            f"[{submission.difficulty}]"
        )
        result = repo.update_file(path, update_msg, content, sha)
    else:
        result = repo.create_file(path, message, content)

    return result["content"].html_url
