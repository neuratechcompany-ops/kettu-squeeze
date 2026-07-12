"""Tests for MCP server and eval framework — Phase 2."""

import json
import tempfile
from pathlib import Path

import pytest

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.api.mcp_server import (
    squeeze_compress,
    squeeze_expand,
    squeeze_read_file,
    squeeze_run_and_compress,
    squeeze_inspect_artifact,
    squeeze_context_status,
)
from kettu_squeeze.analytics.eval_framework import (
    COSResult,
    COSStatus,
    EvalReport,
    EvalRunner,
    MetricResult,
    compute_cos,
)
from kettu_squeeze.types import (
    CompressionMode,
    CompressionRequest,
    ExpandRequest,
    SourceType,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def session_id():
    return "test-mcp-session"


@pytest.fixture
def agent_id():
    return "hermes-test"


@pytest.fixture
def tmp_engine():
    with tempfile.TemporaryDirectory() as td:
        import kettu_squeeze.api.mcp_server as mcp_mod
        old_engine = mcp_mod.engine
        mcp_mod.engine = SqueezeEngine(base_dir=td)
        yield mcp_mod.engine
        mcp_mod.engine = old_engine


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Tool Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMCPCompressExpand:
    """compress → expand возвращает byte-exact исходник."""

    def test_roundtrip_exact(self, tmp_engine, session_id, agent_id):
        content = "line one\nline two\nline three\n"
        result = squeeze_compress(
            content=content,
            session_id=session_id,
            agent_id=agent_id,
        )
        assert "artifact_id" in result

        expanded = squeeze_expand(
            ref=f"artifact:{result['artifact_id']}",
            session_id=session_id,
        )
        assert expanded["content"] == content

    def test_line_range_roundtrip(self, tmp_engine, session_id, agent_id):
        content = "L1\nL2\nL3\nL4\nL5\n"
        result = squeeze_compress(
            content=content,
            session_id=session_id,
            agent_id=agent_id,
        )
        expanded = squeeze_expand(
            ref=f"artifact:{result['artifact_id']}:L2-L4",
            session_id=session_id,
        )
        assert expanded["content"] == "L2\nL3\nL4\n"

    def test_expand_invalid_ref(self, tmp_engine):
        result = squeeze_expand(ref="artifact:nonexistent", session_id="s")
        assert "error" in result

    def test_content_survives_lossless(self, tmp_engine, session_id, agent_id):
        content = "important data line\nmore data\n"
        result = squeeze_compress(
            content=content,
            session_id=session_id,
            agent_id=agent_id,
            mode="lossless",
        )
        assert "important data" in result["content"]

    def test_json_null_stripping(self, tmp_engine, session_id, agent_id):
        content = '{"a": 1, "b": null, "c": 3}'
        # Default lossless: nulls preserved
        result = squeeze_compress(
            content=content,
            session_id=session_id,
            agent_id=agent_id,
            source_type="api",
            mode="lossless",
        )
        # Nulls are lossless by default
        assert '"b":null' in result["content"] or '"b": null' in result["content"]
        assert result["compression_ratio"] >= 1.0


class TestMCPContextSafety:
    """Context ledger и cross-session изоляция."""

    def test_cross_session_ref_denied(self, tmp_engine, agent_id):
        # Session A: store content
        r1 = squeeze_compress(
            content="session-A-data",
            session_id="session-A",
            agent_id=agent_id,
        )

        # Session B: expand the ref — should still work (artifact store is global)
        # BUT context ledger should NOT show it as visible in session B
        status_b = squeeze_context_status(session_id="session-B")
        has_a = any(
            e["artifact_id"] == r1["artifact_id"]
            for e in status_b["entries"]
        )
        assert not has_a, "Session B should not see artifacts from session A"

    def test_eviction_works(self, tmp_engine, agent_id):
        r1 = squeeze_compress(
            content="evict-me-data",
            session_id="evict-session",
            agent_id=agent_id,
        )

        status_before = squeeze_context_status(session_id="evict-session")
        has_before = any(
            e["artifact_id"] == r1["artifact_id"]
            for e in status_before["entries"]
        )
        assert has_before

        # Evict via engine
        import kettu_squeeze.api.mcp_server as mcp_mod
        mcp_mod.engine.evict("evict-session", r1["artifact_id"])

        status_after = squeeze_context_status(session_id="evict-session")
        has_after = any(
            e["artifact_id"] == r1["artifact_id"]
            for e in status_after["entries"]
        )
        assert not has_after

    def test_provenance_different_paths_same_content(
        self, tmp_engine, agent_id
    ):
        content = "same-content"
        r1 = squeeze_compress(
            content=content,
            session_id="prov-session",
            agent_id=agent_id,
            source_type="file",
            source_path="/project/a/config.yaml",
        )
        r2 = squeeze_compress(
            content=content,
            session_id="prov-session",
            agent_id=agent_id,
            source_type="file",
            source_path="/project/b/config.yaml",
        )
        assert r1["artifact_id"] != r2["artifact_id"], (
            "Same content in different paths must have different artifact IDs"
        )

    def test_source_code_not_lossy_by_default(self, tmp_engine, agent_id):
        code = "def authenticate(user, password):\n    if user == 'admin' and password == 'secret':\n        return True\n    return False\n"
        result = squeeze_compress(
            content=code,
            session_id="src-session",
            agent_id=agent_id,
            source_type="file",
            source_path="/src/auth.py",
        )
        # Python files default to STRICT_RAW
        assert "def authenticate" in result["content"]
        assert "return True" in result["content"]
        assert "return False" in result["content"]


class TestMCPReadFile:
    """squeeze_read_file тесты."""

    def test_read_existing_file(self, tmp_engine, session_id, agent_id):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            f.flush()
            result = squeeze_read_file(
                path=f.name,
                session_id=session_id,
                agent_id=agent_id,
            )
        assert "def hello" in result["content"]
        assert result["artifact_id"] is not None

    def test_read_nonexistent(self, tmp_engine, session_id, agent_id):
        result = squeeze_read_file(
            path="/nonexistent/path/file.txt",
            session_id=session_id,
            agent_id=agent_id,
        )
        assert "error" in result

    def test_read_binary_file(self, tmp_engine, session_id, agent_id):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False) as f:
            f.write(b"\x00\x01\x02\xff\xfe")
            f.flush()
            result = squeeze_read_file(
                path=f.name,
                session_id=session_id,
                agent_id=agent_id,
            )
        # Should either succeed or report error
        assert "content" in result or "error" in result


class TestMCPRunAndCompress:
    """squeeze_run_and_compress тесты."""

    def test_run_simple_command(self, tmp_engine, session_id, agent_id):
        result = squeeze_run_and_compress(
            command="echo 'hello world'",
            session_id=session_id,
            agent_id=agent_id,
        )
        assert result["exit_code"] == 0
        assert "hello world" in result["content"]

    def test_run_with_error(self, tmp_engine, session_id, agent_id):
        result = squeeze_run_and_compress(
            command="python -c 'import sys; print(\"error output\", file=sys.stderr); sys.exit(1)'",
            session_id=session_id,
            agent_id=agent_id,
        )
        assert result["exit_code"] == 1

    def test_run_timeout(self, tmp_engine, session_id, agent_id):
        result = squeeze_run_and_compress(
            command="sleep 5",
            session_id=session_id,
            agent_id=agent_id,
            timeout=1,
        )
        assert result["exit_code"] == -1
        assert "timed out" in result.get("error", "").lower()

    def test_source_code_command_not_lossy(self, tmp_engine, session_id, agent_id):
        """Commands that produce source code should not lose content."""
        result = squeeze_run_and_compress(
            command="echo 'def foo():\n    return 42'",
            session_id=session_id,
            agent_id=agent_id,
            source_path="test.py",
        )
        assert "def foo()" in result["content"]


class TestMCPInspect:
    """squeeze_inspect_artifact тесты."""

    def test_inspect_existing(self, tmp_engine, session_id, agent_id):
        r = squeeze_compress(
            content="test content",
            session_id=session_id,
            agent_id=agent_id,
        )
        info = squeeze_inspect_artifact(artifact_id=r["artifact_id"])
        assert info["content_hash"] is not None
        assert info["session_id"] == session_id

    def test_inspect_nonexistent(self, tmp_engine):
        info = squeeze_inspect_artifact(artifact_id="nonexistent")
        assert "error" in info


class TestMCPUnicode:
    """Unicode не вызывает panic."""

    UNICODE_INPUTS = [
        "Привет мир!",
        "你好世界！",
        "مرحبا بالعالم",
        "🎉🔥🚀",
        "日本語テスト",
        "한국어 테스트",
        "a\u0308" * 50,
        "x" * 5000,
        "",
    ]

    def test_unicode_compress_all(self, tmp_engine, session_id, agent_id):
        for text in self.UNICODE_INPUTS:
            result = squeeze_compress(
                content=text,
                session_id=session_id,
                agent_id=agent_id,
            )
            assert "content" in result
            assert result["content"] is not None

    def test_unicode_expand_roundtrip(self, tmp_engine, session_id, agent_id):
        for text in self.UNICODE_INPUTS:
            result = squeeze_compress(
                content=text,
                session_id=session_id,
                agent_id=agent_id,
            )
            expanded = squeeze_expand(
                ref=f"artifact:{result['artifact_id']}",
                session_id=session_id,
            )
            # For lossless/strict_raw content should match
            if "×" not in result["content"] and result.get("mode") != "recoverable_lossy":
                assert expanded["content"] == text, (
                    f"Roundtrip failed for: {text[:50]}"
                )


class TestMCPContextStatus:
    """squeeze_context_status тесты."""

    def test_empty_session(self, tmp_engine):
        status = squeeze_context_status(session_id="empty-session")
        assert status["visible_entries"] == 0

    def test_tracks_entries(self, tmp_engine, session_id, agent_id):
        squeeze_compress(
            content="entry1",
            session_id=session_id,
            agent_id=agent_id,
        )
        squeeze_compress(
            content="entry2",
            session_id=session_id,
            agent_id=agent_id,
        )
        status = squeeze_context_status(session_id=session_id)
        assert status["visible_entries"] >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# Eval Framework Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvalFramework:
    def test_metric_result(self):
        m = MetricResult(name="test", value=0.95, passed=True, threshold=0.9)
        assert m.name == "test"
        assert m.passed is True

    def test_eval_report(self):
        report = EvalReport(group="Test")
        report.metrics.append(
            MetricResult(name="test", value=1.0, passed=True)
        )
        report.total_tests = 1
        report.passed = 1
        assert report.pass_rate == 1.0
        assert report.status == "PASS"

    def test_eval_report_with_hard_gate(self):
        report = EvalReport(group="Test")
        report.metrics.append(
            MetricResult(name="broken_refs", value=1, passed=False, threshold=0)
        )
        report.total_tests = 1
        report.passed = 0
        report.hard_gate_violations.append("broken_references > 0")
        assert report.status == "FAIL"

    def test_cos_pass(self):
        fidelity = EvalReport(group="fidelity")
        fidelity.total_tests = fidelity.passed = 5
        recoverability = EvalReport(group="recoverability")
        recoverability.total_tests = recoverability.passed = 5
        context_safety = EvalReport(group="context_safety")
        context_safety.total_tests = context_safety.passed = 5
        compression = EvalReport(group="compression")
        compression.total_tests = compression.passed = 5
        performance = EvalReport(group="performance")
        performance.total_tests = performance.passed = 5

        result = compute_cos(fidelity, recoverability, context_safety, compression, performance)
        # With all 100% pass rates but empty compression metrics (0 efficiency score),
        # total = 30 + 25 + 20 + 0 + 10 = 85 → GOOD
        assert result.total == 85.0
        assert result.status in (COSStatus.GOOD, COSStatus.EXCELLENT)

    def test_cos_fail_on_hard_gate(self):
        fidelity = EvalReport(group="fidelity")
        fidelity.total_tests = fidelity.passed = 5
        recoverability = EvalReport(group="recoverability")
        recoverability.total_tests = recoverability.passed = 5
        recoverability.hard_gate_violations.append("broken_references > 0")
        context_safety = EvalReport(group="context_safety")
        context_safety.total_tests = context_safety.passed = 5
        compression = EvalReport(group="compression")
        compression.total_tests = compression.passed = 5
        performance = EvalReport(group="performance")
        performance.total_tests = performance.passed = 5

        result = compute_cos(fidelity, recoverability, context_safety, compression, performance)
        assert result.status == COSStatus.FAIL
        assert len(result.hard_gate_violations) > 0

    @pytest.mark.skip(reason="Requires fixture data to exist — run after fixture generation")
    def test_runner_full_eval(self):
        runner = EvalRunner(fixtures_dir="evals/fixtures")
        cos = runner.run_full()
        assert cos.status != COSStatus.FAIL, f"Hard gate violations: {cos.hard_gate_violations}"


# ═══════════════════════════════════════════════════════════════════════════════
# Hard Gate Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHardGates:
    """Проверка hard gate условий."""

    def test_no_broken_refs(self, tmp_engine, session_id, agent_id):
        """После compress, все refs должны быть expandable."""
        content = "L1\nL2\nL3\nL4\nL5\n" * 30
        result = squeeze_compress(
            content=content,
            session_id=session_id,
            agent_id=agent_id,
            source_type="tool",
            source_path="test.log",
            mode="recoverable_lossy",
        )
        refs = result.get("refs", [])
        for ref in refs:
            expanded = squeeze_expand(ref=ref, session_id=session_id)
            assert "error" not in expanded, f"Broken ref: {ref}"

    def test_cross_session_no_leak(self, tmp_engine, agent_id):
        """Session B context status не должен содержать artifact_id из session A."""
        r = squeeze_compress(
            content="secret-A",
            session_id="test-cs-A",
            agent_id=agent_id,
        )
        status = squeeze_context_status(session_id="test-cs-B")
        ids = {e["artifact_id"] for e in status["entries"]}
        assert r["artifact_id"] not in ids

    def test_source_code_not_lossy_default(self, tmp_engine, agent_id):
        """Source code default mode is not lossy."""
        code = "def critical_function():\n    return important_value\n"
        result = squeeze_compress(
            content=code,
            session_id="test-src",
            agent_id=agent_id,
            source_type="file",
            source_path="/project/src/important.py",
        )
        assert not result["lossy"]
        assert "critical_function" in result["content"]
