"""
Kettu Squeeze — types and data models.

All Pydantic models, dataclasses, enums, and constants used across the system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class SourceType(str, Enum):
    FILE = "file"
    TOOL = "tool"
    COMMAND = "command"
    API = "api"


class CompressionMode(str, Enum):
    STRICT_RAW = "strict_raw"
    LOSSLESS = "lossless"
    RECOVERABLE_LOSSY = "recoverable_lossy"


class Visibility(str, Enum):
    FULL = "full"
    SUMMARY = "summary"
    DELTA = "delta"
    REFERENCE = "reference"


# ── Core Models ──────────────────────────────────────────────────────────────

class ClassificationResult(BaseModel):
    """Output of the Input Classifier — metadata about incoming content."""

    source_type: SourceType
    source_path: str | None = None
    mime_type: str = "text/plain"
    encoding: str = "utf-8"
    size_bytes: int = 0
    is_unicode_safe: bool = True


class ArtifactRecord(BaseModel):
    """Immutable record of a stored raw artifact."""

    artifact_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content_hash: str
    source_type: SourceType
    source_path: str | None = None
    mime_type: str = "text/plain"
    encoding: str = "utf-8"
    session_id: str
    agent_id: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    size_bytes: int = 0
    blob_path: str  # relative path within blob store
    parent_artifact_id: str | None = None
    version: int = 1


class ContextEntry(BaseModel):
    """Entry in the Context Ledger — what the model has actually seen."""

    id: int | None = None  # assigned by DB
    session_id: str
    agent_id: str
    conversation_id: str
    artifact_id: str
    representation_id: str
    content_hash: str
    visibility: Visibility
    inserted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    estimated_tokens: int = 0
    context_generation: int = 0
    active: bool = True


class VerificationCheck(BaseModel):
    """Result of a single verification check."""

    name: str
    passed: bool
    detail: str | None = None


class VerificationResult(BaseModel):
    """Aggregate verification result for a compressed representation."""

    passed: bool
    checks: list[VerificationCheck] = Field(default_factory=list)
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CompressionRequest(BaseModel):
    """Request to compress content."""

    content: str
    source_type: SourceType
    source_path: str | None = None
    session_id: str
    agent_id: str
    conversation_id: str = "default"
    mode: CompressionMode = CompressionMode.LOSSLESS
    tokenizer: str = "gpt-oss"
    max_tokens: int | None = None


class CompressionResponse(BaseModel):
    """Response from a compression request."""

    artifact_id: str
    representation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    mode: CompressionMode
    lossy: bool = False
    recoverable: bool = True
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float = 1.0
    content: str
    refs: list[str] = Field(default_factory=list)
    verification: VerificationResult = Field(
        default_factory=lambda: VerificationResult(passed=True, checks=[])
    )


class ExpandRequest(BaseModel):
    """Request to expand a compressed reference."""

    ref: str
    session_id: str


class ExpandResponse(BaseModel):
    """Response from an expand request."""

    artifact_id: str
    content: str
    line_range: str | None = None


class CompressionPolicy(BaseModel):
    """Policy controlling how specific source types are compressed."""

    source_type: SourceType | Literal["*"]
    mode: CompressionMode = CompressionMode.LOSSLESS
    max_repeated_lines: int = 3
    strip_nulls: bool = True
    max_output_tokens: int | None = None
    keep_error_lines: bool = True
    keep_first_n_lines: int = 100
    keep_last_n_lines: int = 50


# ── Default Policies ─────────────────────────────────────────────────────────

DEFAULT_POLICIES: dict[str, CompressionPolicy] = {
    "source_code": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.STRICT_RAW,
        max_repeated_lines=0,
    ),
    "config": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.STRICT_RAW,
    ),
    "sql": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.STRICT_RAW,
    ),
    "log": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.LOSSLESS,
        max_repeated_lines=2,
    ),
    "json": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.LOSSLESS,
        strip_nulls=False,  # null-stripping is semantically lossy — opt-in only
    ),
    "test_output": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.LOSSLESS,
        keep_error_lines=True,
    ),
    "git_diff": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.LOSSLESS,
    ),
    "markdown": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.STRICT_RAW,
    ),
    "default": CompressionPolicy(
        source_type="*",
        mode=CompressionMode.LOSSLESS,
        max_repeated_lines=2,
    ),
}

# Maps source_type / mime_type hints to policy keys
SOURCE_TYPE_POLICY_MAP: dict[str, str] = {
    "python": "source_code",
    "rust": "source_code",
    "javascript": "source_code",
    "typescript": "source_code",
    "go": "source_code",
    "shell": "source_code",
    "java": "source_code",
    "kotlin": "source_code",
    "c": "source_code",
    "cpp": "source_code",
    "ruby": "source_code",
    "text/x-python": "source_code",
    "text/x-rust": "source_code",
    "application/javascript": "source_code",
    "text/x-sh": "source_code",
    "log": "log",
    "test": "test_output",
    "pytest": "test_output",
    "go test": "test_output",
    "cargo test": "test_output",
    "jest": "test_output",
    "json": "json",
    "application/json": "json",
    "git": "git_diff",
    "diff": "git_diff",
    "markdown": "markdown",
    "text/markdown": "markdown",
    "yaml": "config",
    "toml": "config",
    "sql": "sql",
}
