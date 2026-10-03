"""Thin wrapper around PyGithub.

Everything here is blocking network I/O. FastAPI runs the /submit handler in a
threadpool (it's declared `def`, not `async def`), so these calls don't block
the event loop.
"""

from github import Github, GithubException
from github.Repository import Repository

import file_builder
from schema import Submission


def get_repo(token: str, repo_full_name: str) -> Repository:
    return Github(token).get_repo(repo_full_name)


def verify_write_access(token: str, repo_full_name: str, branch: str) -> Repository:
    """Confirm the caller's token can write to this repo + branch.

    Raises the underlying GithubException (401 bad token, 403 no push access,
    404 unknown repo/branch) so the caller can map it to a user-facing error.
    GitHub itself is the source of truth — the backend never trusts the
    payload's repo_owner/repo_name on its own.
    """
    repo = get_repo(token, repo_full_name)
    # Touch the repo: raises 404 if missing/inaccessible, 401 on bad token.
    perms = repo.permissions
    if not (perms and perms.push):
        exc = GithubException(403, {"message": "Token has no push access to this repository"}, {})
        raise exc
    try:
        repo.get_branch(branch)
    except GithubException:
        raise
    return repo


def _get_sha(repo: Repository, path: str, branch: str = 'main') -> str | None:
    """Current blob SHA, or None if the file doesn't exist yet."""
    try:
        contents = repo.get_contents(path, ref=branch)
        if isinstance(contents, list):  # path is a directory
            return None
        return contents.sha
    except GithubException as exc:
        if exc.status == 404:
            return None
        raise


def commit_solution(token: str, repo_full_name: str, branch: str, submission: Submission) -> str:
    """Create or update the solution file. Returns its GitHub URL."""
    repo = get_repo(token, repo_full_name)
    path = file_builder.resolve_path(submission)
    content = file_builder.build_content(submission)
    message = file_builder.commit_message(submission)

    sha = _get_sha(repo, path, branch)
    if sha:
        update_msg = (
            f"chore: update {submission.padded_id}. {submission.title} "
            f"[{submission.difficulty}]"
        )
        result = repo.update_file(path, update_msg, content, sha, branch=branch)
    else:
        result = repo.create_file(path, message, content, branch=branch)

    return result["content"].html_url
