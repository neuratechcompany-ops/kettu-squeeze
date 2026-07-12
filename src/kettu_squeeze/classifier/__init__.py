"""
Input Classifier — determines metadata about incoming content.

Never modifies content. Only inspects to produce ClassificationResult.
"""

from __future__ import annotations

import re

from kettu_squeeze.types import ClassificationResult, SourceType


# Extension → MIME type
_MIME_BY_EXT: dict[str, str] = {
    ".py": "text/x-python",
    ".pyi": "text/x-python",
    ".rs": "text/x-rust",
    ".js": "application/javascript",
    ".ts": "application/typescript",
    ".jsx": "application/javascript",
    ".tsx": "application/typescript",
    ".go": "text/x-go",
    ".sh": "text/x-sh",
    ".bash": "text/x-sh",
    ".zsh": "text/x-sh",
    ".java": "text/x-java",
    ".kt": "text/x-kotlin",
    ".c": "text/x-c",
    ".h": "text/x-c",
    ".cpp": "text/x-c++",
    ".hpp": "text/x-c++",
    ".rb": "text/x-ruby",
    ".json": "application/json",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/toml",
    ".md": "text/markdown",
    ".sql": "text/x-sql",
    ".log": "text/x-log",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".html": "text/html",
    ".css": "text/css",
    ".dockerfile": "text/x-dockerfile",
}


def _mime_from_path(path: str) -> str:
    """Guess MIME type from file extension."""
    for ext, mime in _MIME_BY_EXT.items():
        if path.lower().endswith(ext):
            return mime
    return "text/plain"


def _is_unicode(text: str) -> bool:
    """Check if string is valid Unicode (always true for Python str, but
    explicit for clarity in the pipeline)."""
    try:
        text.encode("utf-8")
        return True
    except UnicodeError:
        return False


class Classifier:
    """Classify incoming content without modifying it."""

    def classify(
        self,
        content: str,
        source_type: SourceType,
        source_path: str | None = None,
    ) -> ClassificationResult:
        """Produce metadata about the content.

        Args:
            content: Raw content as string.
            source_type: Where the content came from.
            source_path: Optional path (e.g. file path, tool name).

        Returns:
            ClassificationResult with metadata.
        """
        mime_type = "text/plain"
        if source_path:
            mime_type = _mime_from_path(source_path)

        size_bytes = len(content.encode("utf-8"))
        is_unicode_safe = _is_unicode(content)

        return ClassificationResult(
            source_type=source_type,
            source_path=source_path,
            mime_type=mime_type,
            encoding="utf-8",
            size_bytes=size_bytes,
            is_unicode_safe=is_unicode_safe,
        )


# Global instance
classifier = Classifier()
