"""Deterministic importance scoring — no LLM, rule-based.

Assigns 0.0 (noise) to 1.0 (critical) based on content patterns.
Every decision must be explainable through `reasons`.
"""

from __future__ import annotations

import re
from kettu_squeeze.policy.models import ImportanceResult

# ── Critical patterns (importance >= 0.9) ──
CRITICAL_PATTERNS: list[tuple[str, str, float]] = [
    # (regex, category, score)
    (r"\b(ERROR|FATAL|CRITICAL|PANIC)\b", "critical_error", 0.95),
    (r"Traceback \(most recent call last\)", "traceback", 0.95),
    (r"\b(CVE-\d{4}-\d{4,})\b", "security_cve", 1.0),
    (r"\b(Access Denied|Permission denied|Unauthorized|Forbidden)\b", "security_auth", 0.95),
    (r"\b(secret|password|token|api_key|private_key)\s*[:=]", "credential_ref", 1.0),
    (r"\bdef\s+\w+\s*\(.*\)\s*(->|:)", "function_def", 0.9),
    (r"\bclass\s+\w+", "class_def", 0.9),
    (r"(?m)^\s*(TODO|FIXME|HACK|XXX|BUG)\b", "code_annotation", 0.85),
    (r"\b(acceptance criteria|must have|requirement)\b", "requirement", 0.85),
]

# ── High importance (0.7-0.9) ──
HIGH_PATTERNS: list[tuple[str, str, float]] = [
    (r"\b(FAILED|FAIL|FAILURE)\b", "test_failure", 0.85),
    (r"\b(WARNING|WARN)\b", "warning", 0.75),
    (r"\b(version|v?\d+\.\d+\.\d+)", "version_info", 0.8),
    (r"\b([a-f0-9]{40})\b", "checksum", 0.8),  # SHA-1/256
    (r"\b(https?://[^\s]+)", "url", 0.8),
    (r"\b(sk-[a-zA-Z0-9]{8,})\b", "api_key_pattern", 1.0),
    (r"\b(sudo|chmod|chown|rm\s+-rf)\b", "dangerous_command", 0.9),
    (r"\b(pytest|npm test|cargo test)\b", "test_command", 0.75),
    (r"\b(docker|kubectl|helm)\b", "ops_command", 0.7),
]

# ── Medium importance (0.4-0.7) ──
MEDIUM_PATTERNS: list[tuple[str, str, float]] = [
    (r"\b(INFO|NOTICE)\b", "info_log", 0.5),
    (r"\b(DEBUG)\b", "debug_log", 0.4),
    (r"\b(OK|SUCCESS)\b", "success_status", 0.4),
    (r"\b(config|setting|option)\s*[:=]", "config_value", 0.65),
    (r"\b(import|from)\s+\w+", "import_stmt", 0.6),
    (r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})", "timestamp", 0.6),
]

# ── Low importance (0.1-0.4) — noise ──
LOW_PATTERNS: list[tuple[str, str, float]] = [
    (r"\b(heartbeat|ping|healthcheck)\b", "heartbeat", 0.15),
    (r"^\s*$", "empty_line", 0.05),
    (r"\b(progress|loading|pending)\b", "progress", 0.2),
    (r"^#+\s", "markdown_heading", 0.35),
]


def score_content(content: str, source_type: str = "unknown") -> ImportanceResult:
    """Score content importance deterministically.

    Returns ImportanceResult with overall score, category, protected fields, and reasons.
    """
    reasons: list[str] = []
    protected: list[str] = []
    max_score = 0.0
    best_category = "unknown"

    all_patterns = [
        (CRITICAL_PATTERNS, "CRITICAL"),
        (HIGH_PATTERNS, "HIGH"),
        (MEDIUM_PATTERNS, "MEDIUM"),
        (LOW_PATTERNS, "LOW"),
    ]

    for patterns, tier in all_patterns:
        for pattern, category, score in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
            if matches:
                if score > max_score:
                    max_score = score
                    best_category = category
                reasons.append(f"{tier}: {category} ({score:.0%}) — {len(matches)} matches")
                if score >= 0.8:
                    for m in matches[:5]:
                        protected.append(str(m)[:80])

    # Boost for source code
    if source_type in ("file", "source_code") and "function_def" not in best_category:
        max_score = max(max_score, 0.7)
        reasons.append("BOOST: source_code type → min importance 0.7")

    # For empty content
    if not content.strip():
        return ImportanceResult(score=0.0, category="empty", reasons=["empty content"])

    return ImportanceResult(
        score=max(max_score, 0.05),  # never absolute zero for non-empty
        category=best_category,
        protected_fields=protected[:10],
        reasons=reasons[:8],
    )


def is_protected(content: str) -> bool:
    """Quick check: does content contain protected information?"""
    protected_patterns = [
        r"\b(sk-[a-zA-Z0-9]{8,})\b",
        r"\b(secret|password|token|api_key|private_key)\s*[:=]",
        r"\b(CVE-\d{4}-\d{4,})\b",
    ]
    for pattern in protected_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False
