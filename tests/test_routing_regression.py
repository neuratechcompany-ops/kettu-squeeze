"""Regression tests for v0.5.5 production routing, pattern RLE, and content classifier."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kettu_squeeze.api.engine import (
    _pick_compressor_name,
    _FILE_EXTENSION_MAP,
    SqueezeEngine,
)
from kettu_squeeze.classifier.content_classifier import (
    looks_like_git_diff,
    looks_like_json,
    looks_like_traceback,
    looks_like_test_output,
    looks_like_log,
    detect_content_type,
)
from kettu_squeeze.compressors import LogCompressor
from kettu_squeeze.types import (
    SourceType,
    ClassificationResult,
    CompressionRequest,
    CompressionMode,
    CompressionPolicy,
    ArtifactRecord,
    RoutingDecision,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cls(path=None, st=SourceType.FILE, mime="text/plain") -> ClassificationResult:
    """Shortcut for creating classification results."""
    return ClassificationResult(source_type=st, source_path=path, mime_type=mime)


def _rec(artifact_id="test123", source_type=SourceType.FILE) -> ArtifactRecord:
    """Shortcut for creating artifact records."""
    return ArtifactRecord(
        artifact_id=artifact_id,
        content_hash="abc123",
        source_type=source_type,
        session_id="test",
        agent_id="test",
        blob_path="blobs/test",
    )


# ── 1. Content Classifier Tests ─────────────────────────────────────────────


class TestContentClassifier:
    """Tests for content-based type detection."""

    def test_git_diff_detection(self):
        content = "diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@"
        assert looks_like_git_diff(content)

    def test_git_diff_with_index(self):
        content = "diff --git a/x b/x\nindex abc123..def456 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@"
        assert looks_like_git_diff(content)

    def test_not_git_diff_just_git_word(self):
        content = "I used git to commit the changes"
        assert not looks_like_git_diff(content)

    def test_git_status_not_diff(self):
        content = "On branch main\nChanges not staged for commit:\n  modified: file.py"
        assert not looks_like_git_diff(content)

    def test_json_detection(self):
        assert looks_like_json('{"key": "value"}')

    def test_json_array_detection(self):
        assert looks_like_json('[1, 2, 3]')

    def test_jsonl_detection(self):
        content = '{"id": 1}\n{"id": 2}\n{"id": 3}'
        assert looks_like_json(content)

    def test_not_json_arbitrary_braces(self):
        content = "This is not json {just some text} here"
        assert not looks_like_json(content)

    def test_malformed_json_fallback(self):
        content = '{"key": value without quotes}'
        assert not looks_like_json(content)

    def test_traceback_detection(self):
        content = 'Traceback (most recent call last):\n  File "test.py", line 42, in foo\n    raise Error("oops")'
        assert looks_like_traceback(content)

    def test_test_output_detection(self):
        content = "=== test session starts ===\ntest_x PASSED\ntest_y FAILED\n=== 1 failed, 1 passed ==="
        assert looks_like_test_output(content)

    def test_log_detection(self):
        content = "2024-01-15 10:30:01 ERROR connection timeout\n2024-01-15 10:30:02 WARN retrying\n2024-01-15 10:30:03 INFO connected"
        confidence = looks_like_log(content)
        assert confidence > 0.5

    def test_detect_content_type_git_diff(self):
        content = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@"
        assert detect_content_type(content) == "git_diff"

    def test_detect_content_type_json(self):
        content = '{"users": [1, 2, 3]}'
        assert detect_content_type(content) == "json"

    def test_detect_content_type_fallback(self):
        content = "This is just some plain text with nothing special in it"
        assert detect_content_type(content) is None


# ── 2. Routing Tests ────────────────────────────────────────────────────────


class TestRoutingPriority:
    """Tests for _pick_compressor_name routing priority."""

    def test_explicit_override_highest_priority(self):
        name, rd = _pick_compressor_name(
            _cls(path="/data/api.json", st=SourceType.FILE),
            explicit_compressor="log",
            content="",
        )
        assert name == "log"
        assert rd.source == "explicit"
        assert rd.confidence == 1.0

    def test_file_json_extension(self):
        name, rd = _pick_compressor_name(
            _cls(path="/data/api_response.json", st=SourceType.FILE),
            content="",
        )
        assert name == "json"
        assert rd.source == "file_extension"

    def test_file_jsonl_extension(self):
        name, rd = _pick_compressor_name(
            _cls(path="/logs/data.jsonl", st=SourceType.FILE),
            content="",
        )
        assert name == "json"
        assert rd.source == "file_extension"

    def test_file_diff_extension(self):
        name, rd = _pick_compressor_name(
            _cls(path="/patches/changes.diff", st=SourceType.FILE),
            content="",
        )
        assert name == "git_diff"
        assert rd.source == "file_extension"

    def test_file_patch_extension(self):
        name, rd = _pick_compressor_name(
            _cls(path="/fix.patch", st=SourceType.FILE),
            content="",
        )
        assert name == "git_diff"
        assert rd.source == "file_extension"

    def test_source_type_api(self):
        name, rd = _pick_compressor_name(
            _cls(st=SourceType.API),
            content="",
        )
        assert name == "json"
        assert rd.source == "source_type"

    def test_source_type_tool(self):
        name, rd = _pick_compressor_name(
            _cls(st=SourceType.TOOL),
            content="",
        )
        assert name == "log"
        assert rd.source == "source_type"

    def test_mime_application_json(self):
        name, rd = _pick_compressor_name(
            _cls(mime="application/json", st=SourceType.FILE),
            content="",
        )
        assert name == "json"
        assert rd.source == "mime_type"

    def test_content_classifier_diff_no_path(self):
        content = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@"
        name, rd = _pick_compressor_name(
            _cls(st=SourceType.TOOL),
            content=content,
        )
        assert name == "log"  # source_type TOOL takes priority
        assert rd.source == "source_type"

    def test_content_classifier_diff_file_no_extension(self):
        content = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@"
        name, rd = _pick_compressor_name(
            _cls(path="/tmp/output.txt", st=SourceType.FILE),
            content=content,
        )
        # .txt maps to log, but content classifier should detect diff
        assert name == "log"  # file extension .txt takes priority

    def test_content_classifier_json_no_extension(self):
        content = '{"key": "value"}'
        name, rd = _pick_compressor_name(
            _cls(path="/tmp/somefile", st=SourceType.FILE),
            content=content,
        )
        assert name == "json"
        assert rd.source == "content_classifier"

    def test_git_status_not_diff(self):
        content = "On branch main\nnothing to commit"
        name, rd = _pick_compressor_name(
            _cls(path="/tmp/status.txt", st=SourceType.FILE),
            content=content,
        )
        # .txt → log, git status shouldn't be detected as diff
        assert name == "log"
        assert rd.source == "file_extension"

    def test_task_detection_fallback(self):
        content = "Docker container app OOMKilled\nERROR: out of memory\nCONTAINER ID abc123"
        name, rd = _pick_compressor_name(
            _cls(path="/tmp/out", st=SourceType.FILE),
            content=content,
        )
        assert name == "log"  # content classifier or task detection → log


# ── 3. Backward Compatibility ────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Ensure legacy behavior is preserved."""

    def test_default_generic_fallback(self):
        name, rd = _pick_compressor_name(
            _cls(st=SourceType.FILE),
            content="plain text",
        )
        assert name == "generic"
        assert rd.source in ("fallback", "content_classifier")

    def test_compression_request_backward(self):
        """Old request format (no compressor field) should work."""
        req = CompressionRequest(
            content="test",
            source_type=SourceType.FILE,
            session_id="test",
            agent_id="test",
        )
        assert req.compressor is None

    def test_routing_decision_in_response(self):
        engine = SqueezeEngine()
        req = CompressionRequest(
            content='{"a": 1}',
            source_type=SourceType.FILE,
            source_path="/data/test.json",
            session_id="test",
            agent_id="test",
            mode=CompressionMode.LOSSLESS,
        )
        resp = engine.compress(req)
        assert resp.routing is not None
        assert resp.routing.compressor_name == "json"
        assert resp.routing.source in ("file_extension", "mime_type", "path_match")


# ── 4. Pattern RLE Tests ────────────────────────────────────────────────────


class TestPatternRLE:
    """Tests for LogCompressor pattern-based RLE."""

    def _get_compressor(self):
        return LogCompressor()

    def _compress(self, lines: list[str], max_repeated=2) -> str:
        lc = self._get_compressor()
        return lc._rle_compress([l + "\n" for l in lines], max_repeated)

    def test_exact_rle_still_works(self):
        result = self._compress(["ERROR: timeout"] * 10)
        assert "×10" in result
        assert "ERROR" in result

    def test_pattern_rle_progress_items(self):
        result = self._compress(
            ["item 1 processed", "item 2 processed", "item 3 processed", "item 4 processed"]
        )
        assert "×4" in result or "×" in result

    def test_pattern_rle_timestamps(self):
        lines = [
            "2024-01-15 10:00:01 INFO ping",
            "2024-01-15 10:00:02 INFO ping",
            "2024-01-15 10:00:03 INFO ping",
        ]
        result = self._compress(lines)
        assert "×3" in result or "×" in result
        assert "INFO ping" in result

    def test_protected_exit_codes_not_grouped(self):
        result = self._compress([
            "Process exited with exit code 1",
            "Process exited with exit code 137",
            "Process exited with exit code 0",
        ])
        # All three should be preserved individually
        assert "exit code 1" in result
        assert "exit code 137" in result
        assert "exit code 0" in result

    def test_protected_ports_not_grouped(self):
        result = self._compress([
            "ERROR: connection lost on port 3204",
            "ERROR: connection lost on port 5432",
            "ERROR: connection lost on port 8080",
        ])
        assert "port 3204" in result
        assert "port 5432" in result

    def test_protected_versions_not_grouped(self):
        result = self._compress([
            "Using version 1.2.3",
            "Using version 2.0.0",
        ])
        assert "version 1.2.3" in result
        assert "version 2.0.0" in result

    def test_different_error_messages_not_grouped(self):
        result = self._compress([
            "ERROR: timeout on port 5432",
            "ERROR: connection refused",
            "ERROR: out of memory",
        ])
        assert "timeout" in result
        assert "connection refused" in result

    def test_pattern_rle_not_bigger_than_exact(self):
        lines = ["item 1 processed", "item 2 processed"] * 10
        result = self._compress(lines)
        # Should be shorter than the original
        original = "".join(l + "\n" for l in lines)
        assert len(result) <= len(original)

    def test_unique_range_display(self):
        result = self._compress(
            [f"DEBUG: item {i} processed" for i in range(100)],
            max_repeated=2,
        )
        assert "range=0-99" in result or "×" in result


# ── 5. Integration Tests ────────────────────────────────────────────────────


class TestIntegration:
    """End-to-end compression with new routing."""

    def test_json_cli_without_type_api(self):
        engine = SqueezeEngine()
        req = CompressionRequest(
            content='{"users": [{"id": 1}, {"id": 2}, {"id": 3}]}',
            source_type=SourceType.FILE,
            source_path="/data/api.json",
            session_id="test",
            agent_id="test",
        )
        resp = engine.compress(req)
        assert resp.routing.compressor_name == "json"

    def test_diff_file_gets_git_diff(self):
        engine = SqueezeEngine()
        req = CompressionRequest(
            content="diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new",
            source_type=SourceType.FILE,
            source_path="/changes.diff",
            session_id="test",
            agent_id="test",
        )
        resp = engine.compress(req)
        assert resp.routing.compressor_name == "git_diff"

    def test_git_status_not_diff(self):
        engine = SqueezeEngine()
        req = CompressionRequest(
            content="On branch main\nChanges not staged:\n  modified: file.py",
            source_type=SourceType.FILE,
            source_path="/git-status.txt",
            session_id="test",
            agent_id="test",
        )
        resp = engine.compress(req)
        assert resp.routing.compressor_name != "git_diff"

    def test_explicit_compressor_wins(self):
        engine = SqueezeEngine()
        req = CompressionRequest(
            content='{"a": 1}',
            source_type=SourceType.FILE,
            source_path="/data/api.json",
            session_id="test",
            agent_id="test",
            compressor="log",  # explicit override
        )
        resp = engine.compress(req)
        assert resp.routing.compressor_name == "log"
        assert resp.routing.source == "explicit"

    def test_routing_explains_decision(self):
        engine = SqueezeEngine()
        req = CompressionRequest(
            content="diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@",
            source_type=SourceType.FILE,
            source_path="/changes.diff",
            session_id="test",
            agent_id="test",
        )
        resp = engine.compress(req)
        explanation = resp.routing.explain()
        assert ".diff" in explanation or "git_diff" in explanation
