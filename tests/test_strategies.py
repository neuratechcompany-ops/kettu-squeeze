"""v0.3 Strategy Framework tests — 8 strategies × contract validation."""

import pytest
import kettu_squeeze.strategies.all_strategies  # trigger registration
from kettu_squeeze.strategies.base import (
    registry, dispatcher, CompressionStrategy, StrategyResult, StrategyCapability,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Registry + Dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistry:
    def test_eight_strategies_registered(self):
        assert registry.count == 8

    def test_all_have_descriptors(self):
        for d in registry.list_all():
            assert d.name
            assert d.version == "0.3.0"
            assert len(d.capabilities) > 0
            assert len(d.supported_formats) > 0

    def test_unique_names(self):
        names = [d.name for d in registry.list_all()]
        assert len(names) == len(set(names))

    def test_by_format(self):
        assert len(registry.by_format("log")) >= 1
        assert len(registry.by_format("json")) >= 1
        assert len(registry.by_format("python")) >= 1

    def test_by_capability(self):
        assert len(registry.by_capability(StrategyCapability.LOSSLESS)) >= 1
        assert len(registry.by_capability(StrategyCapability.INCIDENT_AWARE)) >= 1


class TestDispatcher:
    def test_dispatch_log(self):
        s = dispatcher.dispatch("ERROR: fail", "log")
        assert s is not None and s.descriptor.name == "log_strategy"

    def test_dispatch_json(self):
        s = dispatcher.dispatch('{"a": 1}', "json")
        assert s is not None and s.descriptor.name == "json_strategy"

    def test_dispatch_python(self):
        s = dispatcher.dispatch("def foo(): pass", "python")
        assert s is not None and s.descriptor.name == "python_strategy"

    def test_dispatch_traceback(self):
        s = dispatcher.dispatch("Traceback (most recent call last):", "log")
        assert s is not None and "traceback" in s.descriptor.name

    def test_dispatch_unknown_fallback(self):
        s = dispatcher.dispatch("xyz_unknown_format", "unknown_type")
        assert s is None  # no strategy matches

    def test_has_strategy(self):
        assert dispatcher.has_strategy("log")
        assert not dispatcher.has_strategy("nonexistent_format")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy Contract
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyContract:
    """Every strategy must implement the full contract."""

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_implements_supports(self, name):
        s = registry.get(name)
        assert hasattr(s, 'supports')
        assert callable(s.supports)

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_implements_compress(self, name):
        s = registry.get(name)
        assert hasattr(s, 'compress')

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_implements_expand(self, name):
        s = registry.get(name)
        assert hasattr(s, 'expand')

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_implements_verify(self, name):
        s = registry.get(name)
        assert hasattr(s, 'verify')

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_compress_returns_strategyresult(self, name):
        s = registry.get(name)
        r = s.compress("test", "L1")
        assert isinstance(r, StrategyResult)
        assert r.compressed is not None

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_l0_is_raw(self, name):
        s = registry.get(name)
        content = "test content for L0"
        r = s.compress(content, "L0")
        assert r.compressed == content or r.ratio >= 0.99

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_estimate_returns_compressionestimate(self, name):
        s = registry.get(name)
        est = s.estimate("test", "L1")
        assert est.expected_ratio > 0

    @pytest.mark.parametrize("name", [d.name for d in registry.list_all()])
    def test_explain_returns_list(self, name):
        s = registry.get(name)
        r = s.compress("test", "L1")
        expl = s.explain(r)
        assert isinstance(expl, list)
        assert len(expl) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Log Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogStrategy:
    @pytest.fixture
    def s(self): return registry.get("log_strategy")

    def test_error_preserved(self, s):
        r = s.compress("ERROR: fail\nINFO: ok\n" * 5, "L2")
        assert "ERROR: fail" in r.compressed or r.protected_fields_preserved > 0
        assert r.protected_fields_preserved >= 5

    def test_repeats_folded(self, s):
        content = "INFO: heartbeat\n" * 20
        r = s.compress(content, "L2")
        assert len(r.compressed) < len(content)

    def test_warning_preserved(self, s):
        r = s.compress("WARNING: disk 90%\nINFO: ok\n", "L1")
        assert "WARNING" in r.compressed

    def test_supports_log_format(self, s):
        assert s.supports("any text", "log")
        assert s.supports("docker logs", "docker")

    def test_supports_text_with_errors(self, s):
        assert s.supports("ERROR: failed", "text")

    def test_no_crash_empty(self, s):
        r = s.compress("", "L2")
        assert r.compressed is not None


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestJsonStrategy:
    @pytest.fixture
    def s(self): return registry.get("json_strategy")

    def test_valid_json_compressed(self, s):
        content = '{"a": 1, "b": 2, "c": 3}'
        r = s.compress(content, "L1")
        assert len(r.compressed) > 0
        assert r.ratio <= 1.0

    def test_null_preserved(self, s):
        content = '{"a": null, "b": 1}'
        r = s.compress(content, "L1")
        assert "null" in r.compressed

    def test_invalid_json_passthrough(self, s):
        r = s.compress("not json", "L1")
        assert r.ratio == 1.0

    def test_large_json(self, s):
        items = [{"id": i, "name": f"item_{i}"} for i in range(100)]
        content = '{"results":' + str(items).replace("'", '"') + '}'
        r = s.compress(content, "L2")
        assert r.compressed is not None

    def test_supports_json_auto(self, s):
        assert s.supports('{"a": 1}', "unknown")


# ═══════════════════════════════════════════════════════════════════════════════
# Python Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestPythonStrategy:
    @pytest.fixture
    def s(self): return registry.get("python_strategy")

    def test_strict_raw(self, s):
        code = "def auth(token):\n    return verify(token)\n"
        r = s.compress(code, "L1")
        assert r.compressed == code

    def test_supports_def(self, s):
        assert s.supports("def foo(): pass", "unknown")

    def test_supports_class(self, s):
        assert s.supports("class Foo: pass", "unknown")

    def test_verify_exact(self, s):
        code = "def foo(): return 42"
        r = s.compress(code, "L1")
        assert s.verify(code, r)


# ═══════════════════════════════════════════════════════════════════════════════
# Traceback Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestTracebackStrategy:
    @pytest.fixture
    def s(self): return registry.get("traceback_strategy")

    def test_exception_preserved(self, s):
        tb = 'Traceback (most recent call last):\n  File "x.py", line 42, in foo\nValueError: bad input\n'
        r = s.compress(tb, "L2")
        assert "ValueError" in r.compressed or "bad input" in r.compressed

    def test_file_line_preserved(self, s):
        tb = 'Traceback (most recent call last):\n  File "config.py", line 99, in load\nKeyError: missing\n'
        r = s.compress(tb, "L2")
        assert "config.py" in r.compressed or "99" in r.compressed

    def test_ratio_below_one(self, s):
        tb = 'Traceback:\n  File "a.py", line 1\n  File "b.py", line 2\n' * 5 + 'TypeError: bad\n'
        r = s.compress(tb, "L2")
        assert r.ratio < 1.0

    def test_supports_traceback_keyword(self, s):
        assert s.supports("Traceback (most recent call)", "log")


# ═══════════════════════════════════════════════════════════════════════════════
# Test Output Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestTestOutputStrategy:
    @pytest.fixture
    def s(self): return registry.get("test_output_strategy")

    def test_failures_preserved(self, s):
        out = "test_foo PASSED\ntest_bar FAILED: assert 1 == 2\ntest_baz PASSED\n"
        r = s.compress(out, "L2")
        assert "FAILED" in r.compressed or "test_bar" in r.compressed

    def test_pass_count(self, s):
        r = s.compress("3 passed", "L1")
        assert "passed" in r.compressed.lower()

    def test_supports_test_format(self, s):
        assert s.supports("PASSED", "pytest")


# ═══════════════════════════════════════════════════════════════════════════════
# Diff Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiffStrategy:
    @pytest.fixture
    def s(self): return registry.get("diff_strategy")

    def test_changes_preserved(self, s):
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,4 @@\n-old line\n+new line\n unchanged\n"
        r = s.compress(diff, "L1")
        assert "+new line" in r.compressed or "-old line" in r.compressed

    def test_file_count(self, s):
        diff = "--- a/x.py\n+++ b/x.py\n--- a/y.py\n+++ b/y.py\n"
        r = s.compress(diff, "L1")
        assert "2" in r.compressed or "files" in r.compressed

    def test_supports_diff_markers(self, s):
        assert s.supports("+++ b/file.py", "unknown")


# ═══════════════════════════════════════════════════════════════════════════════
# Markdown Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkdownStrategy:
    @pytest.fixture
    def s(self): return registry.get("markdown_strategy")

    def test_headings_preserved(self, s):
        md = "# Title\n## Section 1\ncontent\n## Section 2\nmore content\n"
        r = s.compress(md, "L1")
        assert "Section 1" in r.compressed or "Section 2" in r.compressed

    def test_structure_extracted(self, s):
        md = "# Doc\n## Intro\n\ntext\n## API\n\nendpoint details\n```\ncode\n```\n"
        r = s.compress(md, "L2")
        assert "Doc" in r.compressed or "sections" in r.compressed.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Conversation Strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationStrategy:
    @pytest.fixture
    def s(self): return registry.get("conversation_strategy")

    def test_decisions_extracted(self, s):
        conv = "User: deploy\nAgent: deploying...\nDecision: use blue-green\nUser: ok\n"
        r = s.compress(conv, "L2")
        assert "blue-green" in r.compressed or "messages" in r.compressed.lower()

    def test_message_count(self, s):
        conv = "User: hi\nAgent: hello\nUser: help\nAgent: sure\n"
        r = s.compress(conv, "L1")
        assert "4" in r.compressed or "messages" in r.compressed.lower()

    def test_supports_chat(self, s):
        assert s.supports("User: hi\nAgent: hello", "chat")


# ═══════════════════════════════════════════════════════════════════════════════
# Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_dispatch_finds_best_strategy(self):
        """Traceback content should go to traceback_strategy, not log_strategy."""
        s = dispatcher.dispatch("Traceback (most recent call last):\nValueError", "log")
        assert "traceback" in s.descriptor.name

    def test_all_strategies_produce_valid_results(self):
        for name in [d.name for d in registry.list_all()]:
            s = registry.get(name)
            r = s.compress("test content for validation", "L1")
            assert r.compressed is not None
            assert r.original_tokens >= 0
            assert r.compressed_tokens >= 0

    def test_registry_count_unchanged(self):
        assert registry.count == 8
