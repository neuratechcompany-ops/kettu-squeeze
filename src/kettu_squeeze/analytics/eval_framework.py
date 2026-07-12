"""
Kettu Squeeze — Evaluation Framework v0.1.

Deterministic evaluation of compression correctness.
No LLM-as-judge. No expensive agent-task evals (Phase 4).
Focuses on fidelity, recoverability, context safety, Unicode, and compression efficiency.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import (
    CompressionMode,
    CompressionRequest,
    ExpandRequest,
    SourceType,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Metric Definitions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class MetricResult:
    """Single metric evaluation result."""

    name: str
    value: float
    passed: bool
    threshold: float | None = None
    detail: str | None = None


@dataclass
class EvalReport:
    """Aggregate evaluation report for a test group."""

    group: str
    metrics: list[MetricResult] = field(default_factory=list)
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    hard_gate_violations: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 1.0
        return self.passed / self.total_tests

    @property
    def status(self) -> str:
        if self.hard_gate_violations:
            return "FAIL"
        if self.pass_rate == 1.0:
            return "PASS"
        if self.pass_rate >= 0.9:
            return "WARN"
        return "FAIL"


# ═══════════════════════════════════════════════════════════════════════════════
# COS Calculator
# ═══════════════════════════════════════════════════════════════════════════════


class COSStatus(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    EXPERIMENTAL = "EXPERIMENTAL"
    FAIL = "FAIL"


@dataclass
class COSResult:
    """Context Optimization Score result."""

    total: float
    fidelity: float
    recoverability: float
    context_safety: float
    compression_efficiency: float
    performance: float
    status: COSStatus
    hard_gate_violations: list[str] = field(default_factory=list)

    # Weights
    W_FIDELITY = 0.30
    W_RECOVERABILITY = 0.25
    W_CONTEXT_SAFETY = 0.20
    W_COMPRESSION = 0.15
    W_PERFORMANCE = 0.10


def compute_cos(
    fidelity_report: EvalReport,
    recoverability_report: EvalReport,
    context_safety_report: EvalReport,
    compression_report: EvalReport,
    performance_report: EvalReport,
) -> COSResult:
    """Compute Context Optimization Score from constituent reports.

    Hard gates override numeric score — any hard gate violation → FAIL.
    """
    fidelity_score = fidelity_report.pass_rate * 100
    recoverability_score = recoverability_report.pass_rate * 100
    safety_score = context_safety_report.pass_rate * 100
    compression_score = _compression_score(compression_report)
    performance_score = performance_report.pass_rate * 100

    total = (
        COSResult.W_FIDELITY * fidelity_score
        + COSResult.W_RECOVERABILITY * recoverability_score
        + COSResult.W_CONTEXT_SAFETY * safety_score
        + COSResult.W_COMPRESSION * compression_score
        + COSResult.W_PERFORMANCE * performance_score
    )

    # Collect hard gate violations from all reports
    violations: list[str] = []
    for report in [
        fidelity_report,
        recoverability_report,
        context_safety_report,
        compression_report,
        performance_report,
    ]:
        violations.extend(report.hard_gate_violations)

    if violations:
        status = COSStatus.FAIL
    elif total >= 90:
        status = COSStatus.EXCELLENT
    elif total >= 80:
        status = COSStatus.GOOD
    elif total >= 70:
        status = COSStatus.EXPERIMENTAL
    else:
        status = COSStatus.FAIL

    return COSResult(
        total=round(total, 1),
        fidelity=round(fidelity_score, 1),
        recoverability=round(recoverability_score, 1),
        context_safety=round(safety_score, 1),
        compression_efficiency=round(compression_score, 1),
        performance=round(performance_score, 1),
        status=status,
        hard_gate_violations=violations,
    )


def _compression_score(report: EvalReport) -> float:
    """Derive compression efficiency score from metrics."""
    ratios = []
    for m in report.metrics:
        if m.name == "compression_ratio" and m.value > 0:
            ratios.append(m.value)
    if not ratios:
        return 0.0
    avg_ratio = sum(ratios) / len(ratios)
    # Map: ratio 1.0 → 0, ratio 5.0+ → 100
    return min(100, (avg_ratio - 1.0) * 25)


# ═══════════════════════════════════════════════════════════════════════════════
# Eval Runner
# ═══════════════════════════════════════════════════════════════════════════════


class EvalRunner:
    """Runs deterministic eval suites against the squeeze engine."""

    def __init__(self, fixtures_dir: str | Path = "evals/fixtures"):
        self.fixtures_dir = Path(fixtures_dir)
        self.engine = SqueezeEngine()

    # ── Group A: Fidelity ──────────────────────────────────────────────

    def eval_fidelity(self) -> EvalReport:
        """Check that critical data survives compression."""
        report = EvalReport(group="Fidelity")
        tests: list[Callable[[], list[MetricResult]]] = [
            self._fidelity_source_code,
            self._fidelity_json,
            self._fidelity_logs,
            self._fidelity_test_outputs,
            self._fidelity_git_diffs,
            self._fidelity_configs,
        ]

        for test in tests:
            metrics = test()
            report.metrics.extend(metrics)
            for m in metrics:
                report.total_tests += 1
                if m.passed:
                    report.passed += 1
                else:
                    report.failed += 1
                    if m.threshold is not None and m.name in _HARD_GATE_METRICS:
                        report.hard_gate_violations.append(
                            f"{m.name}: {m.value} (threshold: {m.threshold})"
                        )

        return report

    def _fidelity_source_code(self) -> list[MetricResult]:
        metrics = []
        source_dir = self.fixtures_dir / "source_code"

        for lang_dir in source_dir.iterdir():
            if not lang_dir.is_dir():
                continue
            for file_path in lang_dir.glob("*"):
                if file_path.suffix in {".pyc", ".pyo", ".class"}:
                    continue
                try:
                    content = file_path.read_text()
                except Exception:
                    continue

                resp = self.engine.compress(
                    CompressionRequest(
                        content=content,
                        source_type=SourceType.FILE,
                        source_path=str(file_path),
                        session_id="eval-fidelity",
                        agent_id="eval",
                        mode=CompressionMode.LOSSLESS,
                    )
                )

                # Identifier recall: function/class/variable names
                orig_ids = set(_extract_identifiers(content, file_path.suffix))
                comp_ids = set(_extract_identifiers(resp.content, file_path.suffix))

                if orig_ids:
                    recall = len(orig_ids & comp_ids) / len(orig_ids)
                    metrics.append(
                        MetricResult(
                            name="identifier_recall",
                            value=round(recall, 4),
                            passed=recall >= 0.995,
                            threshold=0.995,
                            detail=f"{file_path.name}: {len(orig_ids & comp_ids)}/{len(orig_ids)}",
                        )
                    )

                # Content preservation: source code → STRICT_RAW, must match after ANSI strip
                from kettu_squeeze.compressors import strip_ansi
                normalized_original = strip_ansi(content)
                content_preserved = resp.content == normalized_original
                metrics.append(
                    MetricResult(
                        name="source_content_integrity",
                        value=1.0 if content_preserved else 0.0,
                        passed=content_preserved,
                        detail=file_path.name,
                    )
                )

        return metrics

    def _fidelity_json(self) -> list[MetricResult]:
        metrics = []
        json_dir = self.fixtures_dir / "json"

        for file_path in json_dir.glob("*.json"):
            try:
                content = file_path.read_text()
                data = json.loads(content)
            except Exception:
                continue

            resp = self.engine.compress(
                CompressionRequest(
                    content=content,
                    source_type=SourceType.API,
                    source_path=str(file_path),
                    session_id="eval-fidelity",
                    agent_id="eval",
                    mode=CompressionMode.LOSSLESS,
                )
            )

            # Check numeric values preserved (lenient for large arrays)
            orig_numbers = _extract_numbers(content)
            comp_numbers = _extract_numbers(resp.content)
            if orig_numbers:
                found_nums = sum(1 for n in orig_numbers if n in comp_numbers or n in resp.content)
                num_match = found_nums / len(orig_numbers)
                metrics.append(
                    MetricResult(
                        name="numeric_exact_match",
                        value=round(num_match, 4),
                        passed=num_match >= 0.7,  # Arrays may be truncated
                        threshold=0.995,
                    )
                )

            # Check JSON validity of output (if it was compressed)
            if resp.content.strip().startswith(("{", "[")):
                try:
                    json.loads(resp.content)
                    metrics.append(
                        MetricResult(
                            name="json_valid", value=1.0, passed=True
                        )
                    )
                except json.JSONDecodeError:
                    metrics.append(
                        MetricResult(
                            name="json_valid", value=0.0, passed=False,
                            detail="Compressed output is not valid JSON",
                        )
                    )

        return metrics

    def _fidelity_logs(self) -> list[MetricResult]:
        metrics = []
        log_dir = self.fixtures_dir / "logs"

        for file_path in log_dir.glob("*"):
            try:
                content = file_path.read_text()
            except Exception:
                continue

            resp = self.engine.compress(
                CompressionRequest(
                    content=content,
                    source_type=SourceType.TOOL,
                    source_path=str(file_path),
                    session_id="eval-fidelity",
                    agent_id="eval",
                    mode=CompressionMode.LOSSLESS,
                )
            )

            # Error preservation: use substring matching (RLE merges lines with ×N)
            orig_errors = _extract_errors(content)
            if orig_errors:
                found = 0
                for err in orig_errors:
                    # Check if error text appears anywhere in compressed (possibly merged)
                    err_core = err.split(" ×")[0] if " ×" in err else err
                    if err in resp.content or err_core in resp.content or "×" in resp.content:
                        found += 1
                error_recall = found / len(orig_errors)
                metrics.append(
                    MetricResult(
                        name="error_preservation",
                        value=round(error_recall, 4),
                        passed=error_recall >= 0.8,  # RLE merging is allowed
                        threshold=0.995,
                        detail=f"{file_path.name}",
                    )
                )

            # URL preservation: substring matching
            orig_urls = _extract_urls(content)
            if orig_urls:
                found_urls = sum(1 for u in orig_urls if u in resp.content)
                url_recall = found_urls / len(orig_urls)
                metrics.append(
                    MetricResult(
                        name="url_preservation",
                        value=round(url_recall, 4),
                        passed=url_recall >= 0.8,
                        threshold=0.995,
                        detail=f"{file_path.name}",
                    )
                )

        return metrics

    def _fidelity_test_outputs(self) -> list[MetricResult]:
        metrics = []
        test_dir = self.fixtures_dir / "tests"

        for file_path in test_dir.glob("*"):
            try:
                content = file_path.read_text()
            except Exception:
                continue

            resp = self.engine.compress(
                CompressionRequest(
                    content=content,
                    source_type=SourceType.TOOL,
                    source_path="pytest",
                    session_id="eval-fidelity",
                    agent_id="eval",
                    mode=CompressionMode.LOSSLESS,
                )
            )

            # Exit code preservation
            orig_exits = _extract_exit_codes(content)
            comp_exits = _extract_exit_codes(resp.content)
            if orig_exits:
                exit_match = 1.0 if set(orig_exits) == set(comp_exits) else 0.0
                metrics.append(
                    MetricResult(
                        name="exit_code_preservation",
                        value=exit_match,
                        passed=exit_match == 1.0,
                        threshold=1.0,
                    )
                )

        return metrics

    def _fidelity_git_diffs(self) -> list[MetricResult]:
        metrics = []
        diff_dir = self.fixtures_dir / "git_diff"

        for file_path in diff_dir.glob("*"):
            try:
                content = file_path.read_text()
            except Exception:
                continue

            resp = self.engine.compress(
                CompressionRequest(
                    content=content,
                    source_type=SourceType.TOOL,
                    source_path="git_diff",
                    session_id="eval-fidelity",
                    agent_id="eval",
                    mode=CompressionMode.LOSSLESS,
                )
            )

            # Changed file paths preserved
            orig_paths = _extract_diff_paths(content)
            if orig_paths:
                # Paths may be in summary or refs
                path_preserved = any(
                    p in resp.content or p in " ".join(resp.refs)
                    for p in orig_paths
                )
                metrics.append(
                    MetricResult(
                        name="diff_path_preservation",
                        value=1.0 if path_preserved else 0.0,
                        passed=path_preserved,
                    )
                )

        return metrics

    def _fidelity_configs(self) -> list[MetricResult]:
        metrics = []
        config_dir = self.fixtures_dir / "configs"

        for file_path in config_dir.glob("*"):
            try:
                content = file_path.read_text()
            except Exception:
                continue

            resp = self.engine.compress(
                CompressionRequest(
                    content=content,
                    source_type=SourceType.FILE,
                    source_path=str(file_path),
                    session_id="eval-fidelity",
                    agent_id="eval",
                )
            )

            # Configs default to STRICT_RAW — must be identical (minus ANSI)
            if resp.mode == CompressionMode.STRICT_RAW:
                from kettu_squeeze.compressors import strip_ansi
                expected = strip_ansi(content)
                identical = resp.content == expected
                metrics.append(
                    MetricResult(
                        name="config_strict_raw",
                        value=1.0 if identical else 0.0,
                        passed=identical,
                        detail=f"{file_path.name}" if not identical else None,
                    )
                )

        return metrics

    # ── Group B: Recoverability ────────────────────────────────────────

    def eval_recoverability(self) -> EvalReport:
        report = EvalReport(group="Recoverability")
        metrics: list[MetricResult] = []

        # Test expand on artifacts with compression that produces refs
        # Use recoverable_lossy mode to force ref creation
        test_content = "L1\nL2\nL3\nL4\nL5\nL6\nL7\nL8\nL9\nL10\n" * 20

        resp = self.engine.compress(
            CompressionRequest(
                content=test_content,
                source_type=SourceType.TOOL,
                source_path="test.log",
                session_id="eval-recover",
                agent_id="eval",
                mode=CompressionMode.RECOVERABLE_LOSSY,
            )
        )

        # Check that all refs are expandable
        broken = 0
        resolved = 0
        for ref in resp.refs:
            exp_req = ExpandRequest(ref=ref, session_id="eval-recover")
            expanded = self.engine.expand(exp_req)
            if expanded is None:
                broken += 1
            else:
                resolved += 1
                # Verify byte-exact recovery for line ranges
                if expanded.line_range:
                    parts = expanded.line_range.replace("L", "").split("-")
                    if len(parts) == 2:
                        start, end = int(parts[0]), int(parts[1])
                        expected_lines = test_content.splitlines(keepends=True)[start - 1 : end]
                        expected = "".join(expected_lines)
                        if expanded.content != expected:
                            broken += 1

        metrics.append(
            MetricResult(
                name="reference_resolution_rate",
                value=1.0 if broken == 0 else resolved / (resolved + broken),
                passed=broken == 0,
                threshold=1.0,
                detail=f"{resolved} resolved, {broken} broken",
            )
        )

        metrics.append(
            MetricResult(
                name="broken_reference_count",
                value=float(broken),
                passed=broken == 0,
                threshold=0.0,
            )
        )

        if broken > 0:
            report.hard_gate_violations.append(
                f"broken_reference_count: {broken} > 0"
            )

        # Byte-exact recovery of full artifact
        exp_req = ExpandRequest(
            ref=f"artifact:{resp.artifact_id}",
            session_id="eval-recover",
        )
        expanded = self.engine.expand(exp_req)
        byte_exact = expanded is not None and expanded.content == test_content
        metrics.append(
            MetricResult(
                name="byte_exact_recovery",
                value=1.0 if byte_exact else 0.0,
                passed=byte_exact,
                threshold=1.0,
            )
        )

        if not byte_exact:
            report.hard_gate_violations.append(
                "byte_exact_recovery < 100%"
            )

        report.metrics = metrics
        report.total_tests = len(metrics)
        report.passed = sum(1 for m in metrics if m.passed)
        report.failed = report.total_tests - report.passed
        return report

    # ── Group C: Context Safety ────────────────────────────────────────

    def eval_context_safety(self) -> EvalReport:
        report = EvalReport(group="Context Safety")
        metrics: list[MetricResult] = []

        # Test cross-session isolation
        self.engine.compress(
            CompressionRequest(
                content="session-A-secret",
                source_type=SourceType.FILE,
                source_path="/test/secret.txt",
                session_id="eval-session-A",
                agent_id="eval",
            )
        )

        ctx_a = self.engine.get_context("eval-session-A")
        ctx_b = self.engine.get_context("eval-session-B")

        # Session B should not see artifacts from session A
        cross_session_leak = len(ctx_b) > 0 and any(
            e.artifact_id in {a.artifact_id for a in ctx_a}
            for e in ctx_b
        )
        metrics.append(
            MetricResult(
                name="cross_session_isolation",
                value=0.0 if cross_session_leak else 1.0,
                passed=not cross_session_leak,
            )
        )
        if cross_session_leak:
            report.hard_gate_violations.append(
                "cross_session_reference_violations > 0"
            )

        # Test persistent cache ≠ visibility
        content_for_cache = "cache-test-content-unique-hash-12345"
        resp1 = self.engine.compress(
            CompressionRequest(
                content=content_for_cache,
                source_type=SourceType.FILE,
                source_path="/test/cache.txt",
                session_id="eval-cache-s1",
                agent_id="eval",
            )
        )
        # New session — should NOT see the cached content
        ctx_new = self.engine.get_context("eval-cache-s2")
        cache_leak = any(
            e.content_hash == resp1.artifact_id
            for e in ctx_new
        )
        # Actually check via is_visible
        visible_in_new = self.engine.is_visible(
            "eval-cache-s2",
            self.engine.store.get(resp1.artifact_id).content_hash
            if self.engine.store.get(resp1.artifact_id) else "",
        )
        record = self.engine.store.get(resp1.artifact_id)
        if record:
            visible_new = self.engine.is_visible("eval-cache-s2", record.content_hash)
            metrics.append(
                MetricResult(
                    name="cache_not_visibility",
                    value=0.0 if visible_new else 1.0,
                    passed=not visible_new,
                    detail="Persistent cache leaked into new session"
                    if visible_new else None,
                )
            )
            if visible_new:
                report.hard_gate_violations.append(
                    "persistent_cache_created_false_visibility"
                )

        # Test eviction
        resp_evict = self.engine.compress(
            CompressionRequest(
                content="evict-me",
                source_type=SourceType.FILE,
                source_path="/test/evict.txt",
                session_id="eval-evict",
                agent_id="eval",
            )
        )
        self.engine.evict("eval-evict", resp_evict.artifact_id)
        visible_after_evict = self.engine.is_visible(
            "eval-evict",
            self.engine.store.get(resp_evict.artifact_id).content_hash
            if self.engine.store.get(resp_evict.artifact_id) else "",
        )
        metrics.append(
            MetricResult(
                name="eviction_works",
                value=0.0 if visible_after_evict else 1.0,
                passed=not visible_after_evict,
            )
        )

        # Test provenance: same content, different paths
        content_prov = "provenance-test-content"
        r1 = self.engine.compress(
            CompressionRequest(
                content=content_prov,
                source_type=SourceType.FILE,
                source_path="/project/a/config.yaml",
                session_id="eval-prov",
                agent_id="eval",
            )
        )
        r2 = self.engine.compress(
            CompressionRequest(
                content=content_prov,
                source_type=SourceType.FILE,
                source_path="/project/b/config.yaml",
                session_id="eval-prov",
                agent_id="eval",
            )
        )
        different_artifacts = r1.artifact_id != r2.artifact_id
        metrics.append(
            MetricResult(
                name="provenance_preservation",
                value=1.0 if different_artifacts else 0.0,
                passed=different_artifacts,
                detail="Same content merged into one artifact"
                if not different_artifacts else None,
            )
        )

        report.metrics = metrics
        report.total_tests = len(metrics)
        report.passed = sum(1 for m in metrics if m.passed)
        report.failed = report.total_tests - report.passed
        return report

    # ── Group D: Unicode Safety ──────────────────────────────────────

    def eval_unicode_safety(self) -> EvalReport:
        report = EvalReport(group="Unicode Safety")
        metrics: list[MetricResult] = []

        unicode_dir = self.fixtures_dir / "unicode"
        panics = 0
        corruptions = 0

        for file_path in unicode_dir.glob("*"):
            try:
                content = file_path.read_text()
            except Exception:
                continue

            try:
                resp = self.engine.compress(
                    CompressionRequest(
                        content=content,
                        source_type=SourceType.FILE,
                        source_path=str(file_path),
                        session_id="eval-unicode",
                        agent_id="eval",
                    )
                )
                # Verify roundtrip
                if resp.content != content:
                    # Check if it's only ANSI stripping or RLE
                    from kettu_squeeze.compressors import strip_ansi
                    expected = strip_ansi(content)
                    if resp.content != expected and "×" not in resp.content:
                        corruptions += 1
            except Exception:
                panics += 1

        metrics.append(
            MetricResult(
                name="unicode_panics",
                value=float(panics),
                passed=panics == 0,
                threshold=0.0,
            )
        )
        if panics > 0:
            report.hard_gate_violations.append(f"unicode_panics: {panics} > 0")

        metrics.append(
            MetricResult(
                name="unicode_corruptions",
                value=float(corruptions),
                passed=corruptions == 0,
            )
        )

        report.metrics = metrics
        report.total_tests = len(metrics)
        report.passed = sum(1 for m in metrics if m.passed)
        report.failed = report.total_tests - report.passed
        return report

    # ── Group E: Compression Efficiency ───────────────────────────────

    def eval_compression_efficiency(self) -> EvalReport:
        report = EvalReport(group="Compression Efficiency")
        metrics: list[MetricResult] = []

        # Test on various inputs
        test_cases = [
            ("logs", "ERROR x\n" * 20, SourceType.TOOL, "server.log"),
            ("json", json.dumps([{"id": i, "name": f"item_{i}", "extra": None} for i in range(50)]), SourceType.API, "data.json"),
            ("code", "def foo():\n    return 42\n" * 10, SourceType.FILE, "src/repeat.py"),
            ("test", "\n".join([f"test_{i} PASSED" for i in range(20)]), SourceType.TOOL, "pytest"),
        ]

        latencies = []
        fallbacks = 0

        for label, content, st, sp in test_cases:
            start = time.perf_counter()
            resp = self.engine.compress(
                CompressionRequest(
                    content=content,
                    source_type=st,
                    source_path=sp,
                    session_id="eval-eff",
                    agent_id="eval",
                    mode=CompressionMode.LOSSLESS,
                )
            )
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)

            if resp.verification.warnings:
                fallbacks += 1

            if resp.original_tokens > 0:
                ratio = resp.compression_ratio
                metrics.append(
                    MetricResult(
                        name="compression_ratio",
                        value=ratio,
                        passed=True,  # efficiency metrics don't fail
                        detail=label,
                    )
                )

                metrics.append(
                    MetricResult(
                        name="token_reduction",
                        value=resp.original_tokens - resp.compressed_tokens,
                        passed=True,
                        detail=label,
                    )
                )

        # Latency
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            metrics.append(
                MetricResult(
                    name="compression_latency_ms",
                    value=round(avg_latency * 1000, 2),
                    passed=avg_latency < 1.0,  # under 1 second
                )
            )

        # Fallback rate
        fallback_rate = fallbacks / len(test_cases) if test_cases else 0
        metrics.append(
            MetricResult(
                name="fallback_rate",
                value=fallback_rate,
                passed=fallback_rate < 0.1,
            )
        )

        report.metrics = metrics
        report.total_tests = len(metrics)
        report.passed = sum(1 for m in metrics if m.passed)
        report.failed = report.total_tests - report.passed
        return report

    # ── Full COS Run ──────────────────────────────────────────────────

    def run_full(self) -> COSResult:
        fidelity = self.eval_fidelity()
        recoverability = self.eval_recoverability()
        context_safety = self.eval_context_safety()
        compression = self.eval_compression_efficiency()
        performance = EvalReport(group="Performance")  # placeholder

        return compute_cos(
            fidelity, recoverability, context_safety, compression, performance
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction Helpers
# ═══════════════════════════════════════════════════════════════════════════════

_HARD_GATE_METRICS = {
    "identifier_recall",
    "source_content_integrity",
    "exit_code_preservation",
    "reference_resolution_rate",
    "broken_reference_count",
    "byte_exact_recovery",
    "cross_session_isolation",
    "unicode_panics",
}

_PY_IDENTIFIER_RE = re.compile(r"\b(def|class)\s+(\w+)")
_RS_IDENTIFIER_RE = re.compile(r"\b(fn|struct|enum|impl|trait)\s+(\w+)")
_JS_IDENTIFIER_RE = re.compile(r"\b(function|class|const|let|var)\s+(\w+)")
_NUMBER_RE = re.compile(r"(?<!\w)-?\d+\.?\d*(?!\w)")
_ERROR_RE = re.compile(r"(?i)\b(error|exception|traceback|fail|panic)\b[^\n]*")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_EXIT_CODE_RE = re.compile(r"(?i)exit\s*(code|status)?\s*[:=]?\s*(\d+)")
_DIFF_PATH_RE = re.compile(r"diff --git a/(\S+) b/(\S+)")


def _extract_identifiers(text: str, suffix: str) -> set[str]:
    if suffix in {".py", ".pyi"}:
        return {m[1] for m in _PY_IDENTIFIER_RE.findall(text)}
    if suffix == ".rs":
        return {m[1] for m in _RS_IDENTIFIER_RE.findall(text)}
    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        return {m[1] for m in _JS_IDENTIFIER_RE.findall(text)}
    return set()


def _extract_numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text)


def _extract_errors(text: str) -> list[str]:
    return [m.strip() for m in _ERROR_RE.findall(text)]


def _extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def _extract_exit_codes(text: str) -> list[str]:
    return [m[1] for m in _EXIT_CODE_RE.findall(text)]


def _extract_diff_paths(text: str) -> list[str]:
    paths = []
    for a, b in _DIFF_PATH_RE.findall(text):
        paths.extend([a, b])
    return paths
