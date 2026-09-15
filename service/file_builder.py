"""Turns a Submission into a repo path and a .py file body."""

import re

from schema import Submission

DEFAULT_TOPIC = "misc"


def _slugify_topic(tag: str) -> str:
    """'Hash Table' -> 'hash_table', 'Binary Search' -> 'binary_search'."""
    tag = tag.strip().lower()
    tag = re.sub(r"[^a-z0-9]+", "_", tag)
    return tag.strip("_") or DEFAULT_TOPIC


def _slugify_filename(slug: str) -> str:
    """'two-sum' -> 'two_sum'."""
    slug = slug.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "unknown"


def resolve_path(submission: Submission) -> str:
    """topics/<primary_tag>/NNNN_<slug>.py"""
    primary = submission.tags[0] if submission.tags else DEFAULT_TOPIC
    topic = _slugify_topic(primary)
    name = _slugify_filename(submission.slug)
    return f"topics/{topic}/{submission.padded_id}_{name}.py"


def build_content(submission: Submission) -> str:
    """Docstring header + blank line + the solution code."""
    tags = ", ".join(submission.tags) if submission.tags else "—"
    header = (
        '"""\n'
        f"Problem    : {submission.padded_id}. {submission.title}\n"
        f"Link       : {submission.url}\n"
        f"Difficulty : {submission.difficulty}\n"
        f"Tags       : {tags}\n"
        f"Runtime    : {submission.runtime_ms} ms (beats {submission.runtime_percentile}%)\n"
        f"Memory     : {submission.memory_mb} MB (beats {submission.memory_percentile}%)\n"
        '"""\n'
    )
    code = submission.code.rstrip() + "\n"
    return f"{header}\n{code}"


def commit_message(submission: Submission) -> str:
    return f"feat: add {submission.padded_id}. {submission.title} [{submission.difficulty}]"
