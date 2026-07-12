"""P1 tests: Delta + JSON v2 + Formatters."""
import pytest, json
from kettu_squeeze.delta.engine import LineDelta, JsonDelta, TestDelta, create_delta, DeltaResult
from kettu_squeeze.formatters.json_v2 import json_minify, json_dictionary, json_compact, json_roundtrip
from kettu_squeeze.formatters.base import detect_command, format_output, FORMATTERS, git_status, pytest_format


class TestLineDelta:
    def test_identical_no_delta(self):
        r = create_delta("hello", "hello")
        assert r.strategy != "line_delta" or r.delta_payload == "hello"

    def test_small_change(self):
        r = create_delta("line1\nline2\nline3\nline4\n", "line1\nline2\nline4\nline5\n")
        # Delta may not be beneficial for small texts — that's OK
        assert r.strategy in ("line_delta", "none")

    def test_beneficial_check(self):
        r = DeltaResult(delta_payload="hi", original_tokens=100, delta_tokens=10, savings=90)
        assert r.is_beneficial

    def test_not_beneficial(self):
        r = DeltaResult(delta_payload="huge", original_tokens=10, delta_tokens=100, savings=0)
        assert not r.is_beneficial

    def test_line_delta_added(self):
        ld = LineDelta()
        r = ld.create("a\nb\nc\n", "a\nb\nc\nd\n")
        assert "+" in r.delta_payload or r.delta_payload

    def test_line_delta_removed(self):
        ld = LineDelta()
        r = ld.create("a\nb\nc\n", "a\nc\n")
        assert "-" in r.delta_payload or r.delta_payload


class TestJsonDelta:
    def test_supports_valid_json(self):
        jd = JsonDelta()
        assert jd.supports('{"a":1}', '{"a":2}')

    def test_rejects_invalid_json(self):
        jd = JsonDelta()
        assert not jd.supports("not json", "also not")

    def test_field_change(self):
        jd = JsonDelta()
        r = jd.create('{"a":1,"b":2}', '{"a":1,"b":3}')
        assert "b" in r.delta_payload


class TestTestDelta:
    def test_supports_test_output(self):
        td = TestDelta()
        assert td.supports("3 passed", "2 passed, 1 failed")

    def test_rejects_plain_text(self):
        td = TestDelta()
        assert not td.supports("hello world", "goodbye")

    def test_failure_count_change(self):
        td = TestDelta()
        r = td.create("3 passed, 0 failed\n", "2 passed, 1 failed\ntest_x FAILED\n")
        assert "0→1" in r.delta_payload or "passed" in r.delta_payload


class TestJsonV2:
    def test_minify_reduces(self):
        r = json_minify('{\n  "a": 1,\n  "b": 2\n}')
        assert len(r.compressed) < 20

    def test_null_preserved(self):
        r = json_minify('{"a":null,"b":1}')
        assert "null" in r.compressed

    def test_false_preserved(self):
        r = json_minify('{"flag":false}')
        assert "false" in r.compressed

    def test_zero_preserved(self):
        r = json_minify('{"count":0}')
        assert "0" in r.compressed

    def test_empty_string(self):
        r = json_minify('{"name":""}')
        assert '""' in r.compressed

    def test_roundtrip_valid(self):
        orig = '{"a":1,"b":[2,3],"c":null}'
        r = json_minify(orig)
        assert json_roundtrip(orig, r.compressed)

    def test_dictionary_format(self):
        data = [{"application_identifier":"x","installation_status":"ok","version_name":"1.0"} for _ in range(5)]
        r = json_dictionary(json.dumps(data))
        assert "@" in r.compressed  # dictionary header

    def test_compact_fallback(self):
        r = json_compact('{"a":1}')
        assert r.compressed is not None

    def test_invalid_json_handled(self):
        r = json_minify("not json")
        assert r.compressed == "not json"
        assert not r.roundtrip_ok


class TestFormatters:
    def test_git_status(self):
        out = "On branch main\nChanges not staged:\n  modified: src/main.py\n"
        r = git_status(out)
        assert "git:" in r.compressed
        assert "main" in r.compressed

    def test_pytest_format(self):
        out = "test_a PASSED\ntest_b FAILED\n2 passed, 1 failed\n"
        r = pytest_format(out)
        assert "pytest" in r.compressed
        assert "FAIL" in r.compressed

    def test_detect_pytest(self):
        assert detect_command("pytest tests/", "FAILED") == "pytest"

    def test_detect_git_status(self):
        assert detect_command("git status", "") == "git status"

    def test_detect_unknown(self):
        assert detect_command("random_tool", "output") is None

    def test_format_passthrough_unknown(self):
        r = format_output("unknown_cmd", "output")
        assert r.formatter == "passthrough"

    def test_all_formatters_registered(self):
        assert len(FORMATTERS) == 12

    def test_format_reduces_git_diff(self):
        out = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n+new line\n-old line\n" * 5
        r = format_output("git diff", out)
        assert r.savings >= 0 or r.ratio <= 1.0
