"""v0.5 Task-Aware Compression tests."""
import pytest
from kettu_squeeze.tasks.engine import (
    TaskType, TaskDetection, detect_task, plan_content, compress_task_aware,
    KEEP_PATTERNS, DROP_PATTERNS, DETECTION_RULES,
)


class TestTaskDetector:
    def test_debug_from_traceback(self):
        d = detect_task("Traceback (most recent call last):\n  File 'x.py', line 42\nValueError: bad")
        assert d.task == TaskType.DEBUG
        assert d.confidence >= 0.8

    def test_debug_from_error_prompt(self):
        d = detect_task("Why is this crashing? The error says connection refused")
        assert d.task == TaskType.DEBUG

    def test_test_fix_from_pytest(self):
        d = detect_task("test_a FAILED\n2 passed, 1 failed\nFix the test")
        assert d.task == TaskType.TEST_FIX

    def test_docker_from_ps(self):
        d = detect_task("CONTAINER ID  IMAGE\na1b2 nginx Exited (1)")
        assert d.task == TaskType.DOCKER

    def test_kubernetes_from_crash(self):
        d = detect_task("CrashLoopBackOff pod worker-sts-0")
        assert d.task == TaskType.KUBERNETES

    def test_git_from_diff(self):
        d = detect_task("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n+new line")
        assert d.task == TaskType.GIT

    def test_json_from_response(self):
        d = detect_task('{"status":"error","code":500}')
        assert d.task in (TaskType.JSON_API, TaskType.GENERIC)

    def test_root_cause(self):
        d = detect_task("What is the root cause of this outage?")
        assert d.task == TaskType.ROOT_CAUSE

    def test_generic_fallback(self):
        d = detect_task("hello world")
        assert d.task == TaskType.GENERIC
        assert d.confidence < 0.5

    def test_detection_has_reasons(self):
        d = detect_task("ERROR: fail\nTraceback", ["docker ps"])
        assert len(d.reasons) > 0


class TestTaskPlanner:
    def test_debug_keeps_traceback(self):
        ctx = "INFO: start\nERROR: connection refused\nTraceback (most recent call last):\n  File 'x.py', line 42\nValueError\nINFO: done\n"
        result = plan_content(TaskType.DEBUG, ctx)
        assert "Traceback" in result
        assert "ERROR" in result

    def test_test_fix_drops_passed(self):
        ctx = "test_a PASSED\ntest_b FAILED: assert 1==2\ntest_c PASSED\n"
        result = plan_content(TaskType.TEST_FIX, ctx)
        assert "FAILED" in result
        assert "assert" in result

    def test_docker_keeps_error(self):
        ctx = "CONTAINER ID STATUS\na1b2 Exited (137)\nb3c4 Up 3h\nError: OOMKilled\n"
        result = plan_content(TaskType.DOCKER, ctx)
        assert "Exited" in result
        assert "OOMKilled" in result

    def test_generic_keeps_errors(self):
        ctx = "INFO: ok\nERROR: fail\nDEBUG: trace\n"
        result = plan_content(TaskType.GENERIC, ctx)
        assert "ERROR" in result


class TestCompressTaskAware:
    def test_pipeline_runs(self):
        result = compress_task_aware("Fix the bug", "ERROR: fail\nINFO: ok\nTraceback: ValueError\n")
        assert "ERROR" in result
        assert "Traceback" in result

    def test_task_detection_influences_output(self):
        ctx = "INFO: start\nERROR: db timeout\nTraceback (most recent):\n  File 'db.py', line 42\nINFO: done\n"
        debug_r = compress_task_aware("Debug this", ctx)
        log_r = compress_task_aware("Check the logs", ctx)
        assert "Traceback" in debug_r
        assert "ERROR" in log_r
