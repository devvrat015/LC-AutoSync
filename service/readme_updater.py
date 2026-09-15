"""Keeps the problem table in the repo's README.md in sync.

Only the block between <!-- TABLE_START --> and <!-- TABLE_END --> is touched.
Everything above and below is preserved byte-for-byte.
"""

import re

from github import GithubException

import file_builder
from github_client import get_repo
from schema import Submission

START = "<!-- TABLE_START -->"
END = "<!-- TABLE_END -->"

HEADER = (
    "| # | Title | Difficulty | Tags | Runtime | Memory | Solution |\n"
    "|---|-------|------------|------|---------|--------|----------|"
)

SEED_README = f"""# leetcode-solutions

> Auto-synced LeetCode solutions organized by topic.

## Problems

{START}
{HEADER}
{END}
"""


def build_row(submission: Submission) -> str:
    path = file_builder.resolve_path(submission)
    tags = ", ".join(submission.tags) if submission.tags else "—"
    return (
        f"| {submission.problem_id} "
        f"| [{submission.title}]({submission.url}) "
        f"| {submission.difficulty} "
        f"| {tags} "
        f"| {submission.runtime_ms}ms ({submission.runtime_percentile}%) "
        f"| {submission.memory_mb}MB ({submission.memory_percentile}%) "
        f"| [solution]({path}) |"
    )


def _row_id(row: str) -> int:
    """First cell of a table row -> int. Returns -1 for unparseable rows."""
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    try:
        return int(cells[0])
    except (ValueError, IndexError):
        return -1


def _existing_rows(block: str) -> dict[int, str]:
    rows: dict[int, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line):  # separator row
            continue
        pid = _row_id(line)
        if pid >= 0:
            rows[pid] = line
    return rows


def _render_block(rows: dict[int, str]) -> str:
    ordered = [rows[pid] for pid in sorted(rows)]
    return "\n".join([START, HEADER, *ordered, END])


def upsert_row(submission: Submission) -> None:
    repo = get_repo()

    try:
        contents = repo.get_contents("README.md")
        current = contents.decoded_content.decode("utf-8")
        sha = contents.sha
    except GithubException as exc:
        if exc.status != 404:
            raise
        current = SEED_README
        sha = None

    if START not in current or END not in current:
        # README exists but has no table block — append one rather than clobber it.
        current = current.rstrip() + "\n\n## Problems\n\n" + f"{START}\n{HEADER}\n{END}\n"

    before, _, rest = current.partition(START)
    block, _, after = rest.partition(END)

    rows = _existing_rows(block)
    rows[submission.problem_id] = build_row(submission)

    new_content = before + _render_block(rows) + after

    if new_content == current:
        return  # nothing changed, skip an empty commit

    message = f"docs: update problem table ({submission.padded_id}. {submission.title})"
    if sha:
        repo.update_file("README.md", message, new_content, sha)
    else:
        repo.create_file("README.md", message, new_content)
