"""
Compressors — per-type content compression engines.

Each compressor receives raw text and returns compressed text.
All omissions must be marked with recoverable refs.
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from typing import ClassVar

from kettu_squeeze.types import (
    ArtifactRecord,
    CompressionMode,
    CompressionPolicy,
    CompressionResponse,
    VerificationResult,
)


# ── ANSI escape stripper ─────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\].*?\x1b\\")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences without affecting other content."""
    return _ANSI_RE.sub("", text)


# ── Ref utilities ────────────────────────────────────────────────────────────

def make_ref(artifact_id: str, start_line: int, end_line: int) -> str:
    """Create a recoverable reference string."""
    return f"artifact:{artifact_id}:L{start_line}-L{end_line}"


def make_omitted_block(
    artifact_id: str,
    start_line: int,
    end_line: int,
    line_count: int,
) -> str:
    """Create an omitted-block marker with recoverable reference."""
    return (
        f"[omitted: {line_count} lines, "
        f"ref={make_ref(artifact_id, start_line, end_line)}]"
    )


# ── Base Compressor ──────────────────────────────────────────────────────────


class BaseCompressor(ABC):
    """Abstract base for all compressors."""

    name: ClassVar[str] = "base"

    @abstractmethod
    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        """Compress content. Must preserve recoverability for all omissions."""

    def supports_mode(self, mode: CompressionMode) -> bool:
        """Whether this compressor handles the given mode."""
        return True


# ── Log Compressor ───────────────────────────────────────────────────────────


class LogCompressor(BaseCompressor):
    """Lossless log compression: ANSI strip + RLE for repeated lines."""

    name = "log"

    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        content = strip_ansi(content)
        lines = content.splitlines(keepends=True)

        if policy.mode == CompressionMode.STRICT_RAW:
            return content

        if policy.mode == CompressionMode.RECOVERABLE_LOSSY:
            return self._lossy_compress(
                lines, artifact.artifact_id, policy
            )

        # Lossless: RLE only
        return self._rle_compress(lines, policy.max_repeated_lines)

    # ── Pattern RLE (v0.5.5) ─────────────────────────────────────────

    # Patterns safe to normalize (progress counters, timestamps, IDs, etc.)
    _SAFE_NORMALIZE_PATTERNS: list[tuple[str, str, str]] = [
        # progress counters: "item 42 processed"
        (r'(?<![a-zA-Z_])\d+(?![a-zA-Z_])', '<N>', 'progress_counter'),
        # timestamps: ISO-ish
        (r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?', '<TS>', 'timestamp'),
        # request IDs: hex strings 8+ chars
        (r'\b[a-f0-9]{8,64}\b', '<ID>', 'request_id'),
        # durations: "5.2s", "10ms"
        (r'\b\d+(?:\.\d+)?\s*(?:s|ms|µs|ns|sec|min|hour)s?\b', '<DUR>', 'duration'),
        # sequence numbers: standalone or in brackets
        (r'\[?\#?\d+\]?\s+(?:of|/)', '<SEQ> ', 'sequence'),
        # log levels: ERROR, WARN, INFO etc in |LEVEL| or [LEVEL] context
        (r'(?:\| |\[)(?:ERR|WRN|INF|ERROR|WARN|INFO|DEBUG|TRACE|FATAL|CRITICAL)(?: \||\])', '<LVL>', 'log_level'),
    ]

    # Values that MUST NOT be normalized (protected)
    _PROTECTED_PATTERNS: list[tuple[str, str]] = [
        (r'\bexit\s+code\s*[:=]?\s*\d+', 'exit_code'),
        (r'\bstatus\s*(?:code)?\s*[:=]?\s*\d{3}', 'http_status'),
        (r'\bversion\s*[:=]?\s*[\d.]+', 'version'),
        (r'\bport\s*[:=]?\s*\d+', 'port'),
        (r'\bline\s+\d+', 'line_number'),
        (r'\berror\s+code\s*[:=]?\s*\S+', 'error_code'),
    ]

    def _is_protected(self, line: str) -> bool:
        """Check if a line contains protected numeric values."""
        for pattern, _name in self._PROTECTED_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        return False

    def _normalize_pattern(self, line: str) -> str:
        """Normalize safe patterns in a line for RLE grouping."""
        result = line
        for pattern, replacement, _name in self._SAFE_NORMALIZE_PATTERNS:
            result = re.sub(pattern, replacement, result)
        return result

    def _format_rle_label(self, normalized_line: str, count: int) -> str:
        """Add error count label for RLE-compressed error lines."""
        m = re.search(r'<LVL>', normalized_line)
        if m and count > 1:
            # Extract original level from the un-normalized context
            return f"{normalized_line}  [ERROR x{count}]"
        return f"{normalized_line}  x{count}"

    def _pattern_rle_compress(
        self, lines: list[str], max_repeated: int
    ) -> str:
        """Pattern-based RLE that groups similar lines with varying numbers.

        Falls back to exact RLE if pattern grouping loses information.
        """
        if not lines:
            return ""

        result: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Skip protected lines — don't pattern-normalize
            if self._is_protected(line):
                # Exact RLE for protected lines
                count = 1
                while i + count < len(lines) and lines[i + count] == line:
                    count += 1
                if count > max_repeated:
                    result.append(f"{line.rstrip()} ×{count}\n")
                else:
                    for _ in range(count):
                        result.append(line)
                i += count
                continue

            # Try pattern-based grouping
            normalized = self._normalize_pattern(line)
            count = 1
            unique_values: list[str] = [line.rstrip()]
            while i + count < len(lines):
                next_line = lines[i + count]
                if self._is_protected(next_line):
                    break
                next_norm = self._normalize_pattern(next_line)
                if next_norm == normalized:
                    unique_values.append(next_line.rstrip())
                    count += 1
                else:
                    break

            if count > max_repeated:
                # Extract numeric values from unique lines
                nums = []
                for v in unique_values:
                    found = re.findall(r'\b(\d+)\b', v)
                    if found:
                        nums.extend(found)

                if nums:
                    sorted_nums = sorted(set(int(n) for n in nums))
                    if len(sorted_nums) <= 5:
                        range_str = ",".join(str(n) for n in sorted_nums)
                    else:
                        range_str = f"{sorted_nums[0]}-{sorted_nums[-1]}"
                    result.append(f"{normalized.rstrip()} ×{count}; range={range_str}\n")
                else:
                    result.append(f"{normalized.rstrip()} ×{count}\n")
                i += count
            else:
                # Not enough to group — use exact lines
                for j in range(count):
                    result.append(lines[i + j])
                i += count

        return "".join(result)

    def _rle_compress(
        self, lines: list[str], max_repeated: int
    ) -> str:
        """Merge identical consecutive lines with counter (v0.5.5: +pattern RLE)."""
        if not lines:
            return ""

        # Try pattern RLE first
        pattern_result = self._pattern_rle_compress(lines, max_repeated)

        # Exact RLE as baseline
        exact_result_list: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            count = 1
            while (
                i + count < len(lines)
                and lines[i + count] == line
            ):
                count += 1

            if count > max_repeated:
                exact_result_list.append(f"{line.rstrip()} ×{count}\n")
            else:
                for _ in range(count):
                    exact_result_list.append(line)
            i += count
        exact_result = "".join(exact_result_list)

        # Return whichever is shorter (pattern RLE vs exact RLE)
        if len(pattern_result) < len(exact_result):
            return pattern_result
        return exact_result

    def _lossy_compress(
        self,
        lines: list[str],
        artifact_id: str,
        policy: CompressionPolicy,
    ) -> str:
        """Keep head + tail + errors, replace middle with ref."""
        total = len(lines)
        first_n = policy.keep_first_n_lines
        last_n = policy.keep_last_n_lines

        if total <= first_n + last_n + 10:
            # Small enough — lossless
            return self._rle_compress(lines, policy.max_repeated_lines)

        # Collect error lines
        error_pattern = re.compile(
            r"(?i)\b(error|fail|exception|traceback|critical|fatal|panic)\b"
        )
        error_indices: set[int] = set()
        for idx, line in enumerate(lines):
            if error_pattern.search(line):
                error_indices.add(idx)

        # Build result: head + errors + tail
        result: list[str] = []
        seen_omission = False

        for idx, line in enumerate(lines):
            in_head = idx < first_n
            in_tail = idx >= total - last_n
            is_error = idx in error_indices

            if in_head or in_tail or is_error:
                if not in_head and not in_tail and idx > 0 and not seen_omission:
                    omitted_start = first_n
                    omitted_end = idx - 1
                    if omitted_end > omitted_start:
                        result.append(
                            make_omitted_block(
                                artifact_id,
                                omitted_start + 1,
                                omitted_end + 1,
                                omitted_end - omitted_start + 1,
                            )
                            + "\n"
                        )
                        seen_omission = True
                result.append(line)
            elif idx > 0:
                # Track that we're in omission zone
                if not seen_omission:
                    seen_omission = True

        # Add tail omission marker if needed
        last_kept = max(
            [first_n - 1]
            + [i for i in error_indices if i < total - last_n]
            + [0]
        )
        if last_kept < total - last_n - 1:
            result.append(
                make_omitted_block(
                    artifact_id,
                    last_kept + 2,
                    total - last_n,
                    total - last_n - last_kept - 1,
                )
                + "\n"
            )

        return "".join(result)


# ── JSON Compressor ──────────────────────────────────────────────────────────

import json


class JsonCompressor(BaseCompressor):
    """JSON compression: compact encoding, optional null-stripping."""

    name = "json"

    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        if policy.mode == CompressionMode.STRICT_RAW:
            return content

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Not valid JSON — pass through
            return content

        if policy.strip_nulls:
            data = self._strip_nulls(data)

        if policy.mode == CompressionMode.RECOVERABLE_LOSSY:
            data = self._lossy_arrays(
                data, artifact.artifact_id
            )

        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _strip_nulls(obj):
        """Recursively remove keys with null values from objects."""
        if isinstance(obj, dict):
            return {
                k: JsonCompressor._strip_nulls(v)
                for k, v in obj.items()
                if v is not None
            }
        if isinstance(obj, list):
            return [JsonCompressor._strip_nulls(v) for v in obj]
        return obj

    @staticmethod
    def _lossy_arrays(obj, artifact_id: str, max_items: int = 10):
        """Truncate large arrays with recoverable refs."""
        if isinstance(obj, list) and len(obj) > max_items * 2:
            return {
                "_head": obj[:max_items],
                "_tail": obj[-max_items:],
                "_omitted": len(obj) - 2 * max_items,
                "_ref": f"artifact:{artifact_id}",
            }
        if isinstance(obj, dict):
            return {
                k: JsonCompressor._lossy_arrays(v, artifact_id)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [
                JsonCompressor._lossy_arrays(v, artifact_id)
                for v in obj
            ]
        return obj


# ── Test Output Compressor ───────────────────────────────────────────────────


class TestOutputCompressor(BaseCompressor):
    """Test output: keep failures + summary, aggregate passes."""

    name = "test_output"

    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        if policy.mode == CompressionMode.STRICT_RAW:
            return content

        # Try to parse known test formats
        return self._generic_test_compress(content, artifact.artifact_id)

    def _generic_test_compress(
        self, content: str, artifact_id: str
    ) -> str:
        """Generic test output compression."""
        content = strip_ansi(content)
        lines = content.splitlines(keepends=True)

        passed: list[str] = []
        failed: list[str] = []
        summary_lines: list[str] = []
        other: list[str] = []

        fail_pattern = re.compile(
            r"(?i)\b(FAIL|FAILED|FAILURE|ERROR|assert|panic)\b"
        )
        summary_pattern = re.compile(
            r"(?i)\b(passed|failed|error|total|time|duration|result)"
            r"\s*[:=]"
        )

        current_failure: list[str] = []
        in_failure = False

        for line in lines:
            stripped = line.strip()
            if summary_pattern.search(stripped):
                summary_lines.append(line)
                in_failure = False
                if current_failure:
                    failed.append("".join(current_failure))
                    current_failure = []
            elif fail_pattern.search(stripped):
                in_failure = True
                current_failure.append(line)
            elif in_failure:
                # Continue collecting failure context (traceback lines)
                current_failure.append(line)
                # Stop at next test or empty line after traceback
                if re.match(r"^\s*$", stripped) and len(current_failure) > 3:
                    failed.append("".join(current_failure))
                    current_failure = []
                    in_failure = False
            else:
                if re.match(r"(?i)^\s*(PASS|ok|✓)", stripped) or re.search(r"(?i)\b(PASSED|PASS)\b", stripped):
                    passed.append(line)
                else:
                    other.append(line)

        if current_failure:
            failed.append("".join(current_failure))

        # Build output
        result: list[str] = []

        # Failed tests — always full
        if failed:
            result.append(f"── FAILURES ({len(failed)}) ──\n")
            for f in failed:
                result.append(f)
                if not f.endswith("\n"):
                    result.append("\n")
            result.append("\n")

        # Passed tests — aggregated
        if passed:
            result.append(f"✓ {len(passed)} passed\n")
            if len(passed) <= 5:
                for p in passed:
                    result.append(f"  {p}")
            result.append("\n")

        # Summary lines — keep all
        if summary_lines:
            result.append("── SUMMARY ──\n")
            for s in summary_lines:
                result.append(s)
            result.append("\n")

        # Other lines — count, add ref
        if other:
            result.append(
                f"[{len(other)} other output lines, "
                f"ref={make_ref(artifact_id, 1, len(lines))}]\n"
            )

        if not result:
            return content  # Nothing identified — return as-is

        return "".join(result)


# ── Git Diff Compressor ──────────────────────────────────────────────────────


class GitDiffCompressor(BaseCompressor):
    """Git diff: structural summary with full patch recoverable."""

    name = "git_diff"

    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        if policy.mode == CompressionMode.STRICT_RAW:
            return content

        content = strip_ansi(content)
        lines = content.splitlines(keepends=True)

        files: dict[str, dict] = {}
        current_file = None
        additions = 0
        deletions = 0

        for line in lines:
            if line.startswith("diff --git"):
                current_file = line.strip()
                files[current_file] = {"adds": 0, "dels": 0, "hunks": []}
            elif line.startswith("--- a/") or line.startswith("+++ b/"):
                pass  # skip, captured in diff header
            elif line.startswith("@@") and current_file:
                files[current_file]["hunks"].append(line.strip())
            elif line.startswith("+") and not line.startswith("+++"):
                additions += 1
                if current_file:
                    files[current_file]["adds"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
                if current_file:
                    files[current_file]["dels"] += 1

        result: list[str] = []
        result.append(f"── Diff Summary ──\n")
        result.append(f"Files: {len(files)}, +{additions} -{deletions}\n\n")

        for fname, stats in files.items():
            short_name = fname.replace("diff --git ", "")
            result.append(
                f"  {short_name}: +{stats['adds']} -{stats['dels']}"
            )
            if stats["hunks"]:
                result.append(f" ({len(stats['hunks'])} hunks)")
            result.append("\n")

        result.append(
            f"\n[Full diff: {make_ref(artifact.artifact_id, 1, len(lines))}]\n"
        )

        return "".join(result)


# ── Source Code Compressor ───────────────────────────────────────────────────


class SourceCodeCompressor(BaseCompressor):
    """Source code: STRICT_RAW by default. No removal without explicit policy."""

    name = "source_code"

    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        if policy.mode == CompressionMode.STRICT_RAW:
            return strip_ansi(content)

        if policy.mode == CompressionMode.LOSSLESS:
            # Only safe transformations
            return strip_ansi(content)

        if policy.mode == CompressionMode.RECOVERABLE_LOSSY:
            return self._summary_compress(
                content, artifact.artifact_id
            )

        return content

    def _summary_compress(
        self, content: str, artifact_id: str
    ) -> str:
        """Symbol index + outline with recoverable refs."""
        content = strip_ansi(content)
        lines = content.splitlines(keepends=True)

        imports: list[str] = []
        functions: list[str] = []
        classes: list[str] = []

        import_re = re.compile(
            r"^\s*(import|from)\s+\w+"
        )
        func_re = re.compile(
            r"^\s*(def|fn|func|function)\s+(\w+)"
        )
        class_re = re.compile(
            r"^\s*(class)\s+(\w+)"
        )

        for i, line in enumerate(lines, 1):
            if import_re.match(line):
                imports.append(f"  L{i}: {line.strip()}")
            elif func_re.match(line):
                functions.append(f"  L{i}: {line.strip()}")
            elif class_re.match(line):
                classes.append(f"  L{i}: {line.strip()}")

        result: list[str] = []
        result.append(f"[Source outline: {len(lines)} lines]\n")

        if imports:
            result.append(f"\nImports ({len(imports)}):\n")
            result.extend(imports[:20])
            if len(imports) > 20:
                result.append(f"  ... +{len(imports) - 20} more\n")

        if classes:
            result.append(f"\nClasses ({len(classes)}):\n")
            result.extend(classes)

        if functions:
            result.append(f"\nFunctions ({len(functions)}):\n")
            result.extend(functions[:30])
            if len(functions) > 30:
                result.append(f"  ... +{len(functions) - 30} more\n")

        result.append(
            f"\n[Full source: {make_ref(artifact_id, 1, len(lines))}]\n"
        )

        return "".join(result)


# ── Generic Compressor ───────────────────────────────────────────────────────


class GenericCompressor(BaseCompressor):
    """Fallback compressor — lossless only, ANSI strip + basic dedup."""

    name = "generic"

    def compress(
        self,
        content: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> str:
        if policy.mode == CompressionMode.STRICT_RAW:
            return content

        # Lossless: strip ANSI only
        return strip_ansi(content)


# ── Compressor Registry ──────────────────────────────────────────────────────


COMPRESSORS: dict[str, BaseCompressor] = {
    "log": LogCompressor(),
    "json": JsonCompressor(),
    "test_output": TestOutputCompressor(),
    "git_diff": GitDiffCompressor(),
    "source_code": SourceCodeCompressor(),
    "generic": GenericCompressor(),
}
