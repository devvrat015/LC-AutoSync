"""Turns a Submission into a repo path and a .py file body."""

import re

from schema import Submission

DEFAULT_TOPIC = "misc"

LANGUAGE_EXTENSIONS = {
    "python3": ".py", "python": ".py", "java": ".java", "cpp": ".cpp", "c": ".c",
    "javascript": ".js", "typescript": ".ts", "golang": ".go", "rust": ".rs",
    "ruby": ".rb", "swift": ".swift", "kotlin": ".kt", "scala": ".scala",
    "php": ".php", "csharp": ".cs", "dart": ".dart", "racket": ".rkt",
    "erlang": ".erl", "elixir": ".ex", "mysql": ".sql", "mssql": ".sql",
    "oraclesql": ".sql", "pythondata": ".py", "postgresql": ".sql", "bash": ".sh",
    "react": ".jsx", "pandas": ".py"
}

COMMENT_STYLES = {
    ".py": ('"""', '"""'),
    ".java": ('/*', '*/'), ".js": ('/*', '*/'), ".ts": ('/*', '*/'),
    ".cpp": ('/*', '*/'), ".c": ('/*', '*/'), ".go": ('/*', '*/'),
    ".rs": ('/*', '*/'), ".swift": ('/*', '*/'), ".kt": ('/*', '*/'),
    ".scala": ('/*', '*/'), ".cs": ('/*', '*/'), ".dart": ('/*', '*/'),
    ".php": ('/*', '*/'), ".sql": ('/*', '*/'),
    ".rb": ('=begin', '=end'),
    ".sh": (": '", "'"), 
    ".rkt": ('#|', '|#'),
    ".erl": ('%{', '%}'), ".ex": ('%{', '%}')
}


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
    """topics/<primary_tag>/NNNN_<slug>.<ext>

    Both parts are slugified (regex allow-list), so path traversal is not
    possible — but verify explicitly as defense in depth.
    """
    primary = submission.tags[0] if submission.tags else DEFAULT_TOPIC
    topic = _slugify_topic(primary)
    name = _slugify_filename(submission.slug)
    ext = LANGUAGE_EXTENSIONS.get(submission.language, '.py')
    path = f"topics/{topic}/{submission.padded_id}_{name}{ext}"
    if ".." in path or not path.startswith("topics/"):
        raise ValueError(f"unsafe generated path: {path!r}")
    return path


def build_content(submission: Submission) -> str:
    """Docstring header + blank line + the solution code."""
    tags = ", ".join(submission.tags) if submission.tags else "—"
    ext = LANGUAGE_EXTENSIONS.get(submission.language, '.py')
    c_start, c_end = COMMENT_STYLES.get(ext, ('#', '#'))
    header = (
        f"{c_start}\n"
        f"Problem    : {submission.padded_id}. {submission.title}\n"
        f"Link       : {submission.url}\n"
        f"Difficulty : {submission.difficulty}\n"
        f"Tags       : {tags}\n"
        f"Runtime    : {submission.runtime_ms} ms (beats {submission.runtime_percentile}%)\n"
        f"Memory     : {submission.memory_mb} MB (beats {submission.memory_percentile}%)\n"
        f"{c_end}\n"
    )
    code = submission.code.rstrip() + "\n"
    return f"{header}\n{code}"


def commit_message(submission: Submission) -> str:
    return f"feat: add {submission.padded_id}. {submission.title} [{submission.difficulty}]"
