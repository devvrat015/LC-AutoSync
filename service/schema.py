"""Payload schema for incoming submissions.

Pydantic replaces the dataclass from the original plan: validation happens
automatically at the FastAPI boundary, so `/submit` never sees a half-built
Submission. Missing fields are turned into a 400 by the handler in main.py.
"""

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

# Conservative bounds for a public endpoint. LeetCode solutions are small;
# 100k chars (~100KB) is far above any real submission.
MAX_CODE_CHARS = 100_000
MAX_TITLE_CHARS = 200
MAX_SLUG_CHARS = 100
MAX_TAGS = 10
MAX_TAG_CHARS = 50

REPO_PART_PATTERN = r"^[A-Za-z0-9_.-]+$"
BRANCH_PATTERN = r"^[A-Za-z0-9_.\-/]+$"
SLUG_PATTERN = r"^[a-z0-9-]+$"

# Languages observed from LeetCode's submission API (lang.name). Anything else
# falls back to a .py extension + '#' comments in file_builder.
KNOWN_LANGUAGES = {
    "python3", "python", "java", "cpp", "c", "javascript", "typescript",
    "golang", "rust", "ruby", "swift", "kotlin", "scala", "php", "csharp",
    "dart", "racket", "erlang", "elixir", "mysql", "mssql", "oraclesql",
    "pythondata", "postgresql", "bash", "react", "pandas",
}


class Submission(BaseModel):
    problem_id: int = Field(gt=0, lt=100_000)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    slug: str = Field(min_length=1, max_length=MAX_SLUG_CHARS, pattern=SLUG_PATTERN)
    difficulty: Literal["Easy", "Medium", "Hard"] = "Easy"
    tags: List[str] = Field(default_factory=list, max_length=MAX_TAGS)
    runtime_ms: int = Field(ge=0, le=1_000_000)
    memory_mb: float = Field(ge=0, le=1_000_000)
    runtime_percentile: float = Field(ge=0, le=100)
    memory_percentile: float = Field(ge=0, le=100)
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    language: str = Field(default="python3", min_length=1, max_length=32)
    repo_owner: str = Field(min_length=1, max_length=64, pattern=REPO_PART_PATTERN)
    repo_name: str = Field(min_length=1, max_length=128, pattern=REPO_PART_PATTERN)
    branch: str = Field(default="main", min_length=1, max_length=128, pattern=BRANCH_PATTERN)

    @field_validator("repo_owner", "repo_name", "branch")
    @classmethod
    def _no_dot_segments(cls, v: str) -> str:
        # Git itself forbids `..` in refs; `.`/`..` path segments must never
        # appear even though `.`/`/` are otherwise legal characters.
        segments = v.split("/")
        if any(s in (".", "..") for s in segments):
            raise ValueError("must not contain '.' or '..' segments")
        if v in (".", ".."):
            raise ValueError("must not be '.' or '..'")
        return v

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        # Commit messages and README rows are single-line; drop control chars.
        v = " ".join(v.split())
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: List[str]) -> List[str]:
        cleaned = [" ".join(t.split()) for t in v]
        cleaned = [t for t in cleaned if t][:MAX_TAGS]
        for t in cleaned:
            if len(t) > MAX_TAG_CHARS:
                raise ValueError(f"tag too long: {t[:20]}...")
        return cleaned

    @field_validator("language")
    @classmethod
    def _clean_language(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("language must not be blank")
        # Unknown languages are accepted (fallback extension) but normalized.
        return v if v in KNOWN_LANGUAGES else v[:32]

    @property
    def padded_id(self) -> str:
        return str(self.problem_id).zfill(4)

    @property
    def url(self) -> str:
        return f"https://leetcode.com/problems/{self.slug}/"


class SubmitResponse(BaseModel):
    status: str
    url: str | None = None
    message: str | None = None

class CodeExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1024)
    # The exact redirect URI the extension used in the authorize request.
    # Forwarded to GitHub so both halves of the flow agree; derived from
    # chrome.identity.getRedirectURL(), never hardcoded.
    redirect_uri: str | None = Field(default=None, max_length=512)

class GitHubUser(BaseModel):
    login: str
    name: str | None = None
    avatar_url: str | None = None

class RepoInfo(BaseModel):
    full_name: str
    name: str
    private: bool
    default_branch: str

class BranchInfo(BaseModel):
    name: str
