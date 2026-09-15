"""Payload schema for incoming submissions.

Pydantic replaces the dataclass from the original plan: validation happens
automatically at the FastAPI boundary, so `/submit` never sees a half-built
Submission. Missing fields are turned into a 400 by the handler in main.py.
"""

from typing import List

from pydantic import BaseModel, Field


class Submission(BaseModel):
    problem_id: int
    title: str
    slug: str
    difficulty: str
    tags: List[str] = Field(default_factory=list)
    runtime_ms: int
    memory_mb: float
    runtime_percentile: float
    memory_percentile: float
    code: str

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
