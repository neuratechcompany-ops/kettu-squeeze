"""
Content-based classifier for compressor routing fallback.

Detects content type from raw text when path/MIME signals are unavailable.
"""
from __future__ import annotations

import json
import re
from typing import Optional


# ── Git diff markers ──────────────────────────────────────────────────────────

_GIT_DIFF_HEADER = re.compile(
    r"^diff\s--git\s", re.MULTILINE
)
_GIT_DIFF_MARKERS = [
    "diff --git",
    "--- a/",
    "+++ b/",
    "@@ ",
    "index ",
    "new file mode",
    "deleted file mode",
    "rename from",
    "rename to",
    "similarity index",
    "Binary files",
]
_GIT_DIFF_PATTERNS = [
    re.compile(r"^diff\s--git\s"),
    re.compile(r"^index\s[0-9a-f]+\.\.[0-9a-f]+", re.MULTILINE),
    re.compile(r"^@@\s-\d+(?:,\d+)?\s\+\d+(?:,\d+)?\s@@", re.MULTILINE),
]


# ── Traceback markers ─────────────────────────────────────────────────────────

_TRACEBACK_PATTERN = re.compile(
    r"Traceback\s*\(most\s+recent\s+call\s+last\)",
    re.IGNORECASE,
)
_PYTHON_TRACEBACK_LINE = re.compile(
    r'^\s*File\s+".+",\s+line\s+\d+,\s+in\s+\w+',
    re.MULTILINE,
)


# ── Test output markers ───────────────────────────────────────────────────────

_TEST_SUMMARY_PATTERN = re.compile(
    r"=+\s*(test\s+session|short\s+test\s+summary)",
    re.IGNORECASE,
)
_TEST_RESULT_PATTERNS = [
    re.compile(r"(?:PASSED|FAILED|ERROR|SKIPPED|XPASS|XFAIL)\b", re.IGNORECASE),
    re.compile(r"\d+\s+(?:passed|failed|error)", re.IGNORECASE),
    re.compile(r"=+.*\d+\s+passed.*=+", re.IGNORECASE),
]


# ── Log markers ────────────────────────────────────────────────────────────────

# If more than N% of lines match log-like patterns, classify as log
_LOG_PATTERNS = [
    re.compile(r"\b(?:ERR|WRN|INF|ERROR|WARN|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b"),
    re.compile(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}"),
    re.compile(r"\[(?:ERR|WRN|INF|ERROR|WARN|INFO|DEBUG|TRACE|FATAL|CRITICAL)\]"),
]


# ── Detection functions ────────────────────────────────────────────────────────


def looks_like_git_diff(content: str) -> bool:
    """Check if content matches git diff structure."""
    if not content.strip():
        return False

    # Must start with or contain "diff --git"
    if not _GIT_DIFF_HEADER.search(content):
        return False

    # Require at least 2 markers
    markers_found = 0
    for marker in _GIT_DIFF_MARKERS:
        if marker in content:
            markers_found += 1
            if markers_found >= 2:
                return True

    return False


def looks_like_json(content: str) -> bool:
    """Check if content is valid JSON or JSONL/NDJSON.

    Returns True only for parseable JSON, not arbitrary text with braces.
    """
    if not content.strip():
        return False

    # Try single JSON value
    try:
        json.loads(content)
        return True
    except (json.JSONDecodeError, ValueError):
        pass

    # Try JSONL / NDJSON
    lines = content.strip().splitlines()
    if len(lines) >= 2:
        valid_lines = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                valid_lines += 1
            except (json.JSONDecodeError, ValueError):
                break

        # Require at least 2 valid JSON lines to classify as JSONL
        if valid_lines >= 2:
            return True

    return False


def looks_like_traceback(content: str) -> bool:
    """Check if content is a Python/stack traceback."""
    if _TRACEBACK_PATTERN.search(content):
        return True

    # Multi-file traceback without header
    file_lines = _PYTHON_TRACEBACK_LINE.findall(content)
    if len(file_lines) >= 2 and any(
        marker in content for marker in ("Error:", "Exception:", "raise ")
    ):
        return True

    return False


def looks_like_test_output(content: str) -> bool:
    """Check if content is test runner output."""
    if _TEST_SUMMARY_PATTERN.search(content):
        return True

    # Count test result markers
    test_markers = sum(
        1 for p in _TEST_RESULT_PATTERNS if p.search(content)
    )
    return test_markers >= 2


def looks_like_log(content: str) -> float:
    """Check if content looks like log output. Returns confidence 0..1."""
    if not content.strip():
        return 0.0

    lines = content.splitlines()
    if not lines:
        return 0.0

    log_lines = 0
    for line in lines:
        for pattern in _LOG_PATTERNS:
            if pattern.search(line):
                log_lines += 1
                break

    ratio = log_lines / max(len(lines), 1)
    # Require at least 20% of lines to match log patterns
    if ratio >= 0.2:
        return min(ratio, 1.0)
    return 0.0


def detect_content_type(content: str) -> Optional[str]:
    """Return compressor name based on content analysis, or None if uncertain.

    Priority order:
    1. Git diff (structural markers)
    2. Traceback (distinctive pattern)
    3. Test output (distinctive pattern)
    4. JSON (parse-based, most reliable)
    5. Log (heuristic, lowest confidence)
    """
    if looks_like_git_diff(content):
        return "git_diff"

    if looks_like_traceback(content):
        return "log"  # traceback is handled by log compressor

    if looks_like_test_output(content):
        return "test_output"

    if looks_like_json(content):
        return "json"

    log_confidence = looks_like_log(content)
    if log_confidence >= 0.3:
        return "log"

    return None
