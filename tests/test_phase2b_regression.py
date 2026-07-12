"""Phase 2B regression tests — from comparative findings."""

import pytest
from kettu_squeeze.policy.engine import AdaptivePolicyEngine
from kettu_squeeze.policy.models import ContextBudget, CompressionAction, CompressionLevel, CompressionDecision
from kettu_squeeze.policy.execution import ExecutionMode
from kettu_squeeze.policy.bridge import EngineBridge
from kettu_squeeze.shadow.models import ShadowComparator, ComparisonVerdict


class TestKeepRawOverrides:
    """57 KEEP_RAW overrides — verify they are safe, not bugs."""

    @pytest.fixture
    def engine(self):
        return AdaptivePolicyEngine()

    def test_keep_raw_on_critical_error(self, engine):
        d = engine.decide("ERROR: CVE-2026-0001 critical vulnerability\n", "log")
        assert d.action == CompressionAction.KEEP_RAW

    def test_keep_raw_on_traceback(self, engine):
        d = engine.decide("Traceback (most recent call last):\n  File 'x.py', line 42\n", "log")
        assert d.action == CompressionAction.KEEP_RAW

    def test_keep_raw_on_api_key(self, engine):
        d = engine.decide("api_key: sk-1234567890abcdef", "config")
        assert d.action == CompressionAction.KEEP_RAW

    def test_keep_raw_source_code(self, engine):
        d = engine.decide("def authenticate(token): return verify(token)", "source_code")
        assert d.action == CompressionAction.KEEP_RAW

    def test_compress_warning_under_pressure(self, engine):
        budget = ContextBudget(current_tokens=120000, model_context_limit=131072)  # CRITICAL
        d = engine.decide("WARNING: disk usage at 85%\n" * 100, "log", budget)
        assert d.action != CompressionAction.KEEP_RAW

    def test_externalize_huge_payload(self, engine):
        budget = ContextBudget(current_tokens=120000, model_context_limit=131072)
        content = "data: " + "X" * 15000  # >5000 tokens
        d = engine.decide(content, "log", budget)
        assert d.action == CompressionAction.EXTERNALIZE

    def test_level_escalation_under_pressure(self, engine):
        budget_low = ContextBudget(current_tokens=30000, model_context_limit=131072)
        budget_high = ContextBudget(current_tokens=120000, model_context_limit=131072)
        content = "INFO: ok\n" * 200
        d_low = engine.decide(content, "log", budget_low)
        d_high = engine.decide(content, "log", budget_high)
        assert d_low.level.value <= d_high.level.value


class TestComparatorWinners:
    @pytest.fixture
    def comparator(self):
        return ShadowComparator()

    def test_hard_gate_failure_automatic_loss(self, comparator):
        from kettu_squeeze.policy.execution import ExecutionReport
        legacy = ExecutionReport(input_tokens=1000, output_tokens=500)
        adaptive = ExecutionReport(input_tokens=1000, output_tokens=300, hard_gate_failures=["broken_ref"])
        decision = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2)
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict == ComparisonVerdict.LEGACY_WIN

    def test_protected_field_loss_automatic_loss(self, comparator):
        from kettu_squeeze.policy.execution import ExecutionReport
        legacy = ExecutionReport(input_tokens=1000, output_tokens=500, protected_fields_preserved=5)
        adaptive = ExecutionReport(input_tokens=1000, output_tokens=300, protected_fields_preserved=3)
        decision = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2)
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict == ComparisonVerdict.LEGACY_WIN

    def test_small_savings_not_winner(self, comparator):
        from kettu_squeeze.policy.execution import ExecutionReport
        legacy = ExecutionReport(input_tokens=1000, output_tokens=500)
        adaptive = ExecutionReport(input_tokens=1000, output_tokens=490)  # 2% better
        decision = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2)
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict in (ComparisonVerdict.TIE, ComparisonVerdict.LEGACY_WIN)


class TestRealExecution:
    @pytest.fixture
    def bridge(self):
        return EngineBridge()

    def test_legacy_mode_works(self, bridge):
        resp, report, _ = bridge.compress("test log", mode=ExecutionMode.LEGACY)
        assert resp is not None
        assert report is not None

    def test_adaptive_mode_works(self, bridge):
        resp, report, _ = bridge.compress("test log", mode=ExecutionMode.ADAPTIVE)
        assert resp is not None
        assert report is not None

    def test_shadow_mode_works(self, bridge):
        resp, report, shadow = bridge.compress("test log", mode=ExecutionMode.SHADOW)
        assert resp is not None
        assert shadow is not None

    def test_keep_raw_preserves_content(self, bridge):
        content = "CRITICAL: CVE-2026-0001"
        resp, _, _ = bridge.compress(content, source_type="log", mode=ExecutionMode.ADAPTIVE)
        assert "CVE-2026-0001" in resp.content

    def test_protected_fields_survive(self, bridge):
        content = "api_key: sk-secret-test-123"
        budget = ContextBudget(current_tokens=30000, model_context_limit=131072)
        resp, _, _ = bridge.compress(content, source_type="config", mode=ExecutionMode.ADAPTIVE,
                                       context_budget=budget)
        assert "sk-secret-test-123" in resp.content


class TestHoldoutIsolation:
    """Verify holdout not contaminated by calibration."""

    def test_holdout_not_in_calibration(self):
        import yaml
        from pathlib import Path
        data = yaml.safe_load((Path("datasets/adaptive-policy-v1") / "scenarios" / "scenarios.yaml").read_text())
        cal_ids = {s['scenario_id'] for s in data['scenarios'] if s['split'] == 'calibration'}
        ho_ids = {s['scenario_id'] for s in data['scenarios'] if s['split'] == 'holdout'}
        assert len(cal_ids & ho_ids) == 0  # no overlap

    def test_holdout_count(self):
        import yaml
        from pathlib import Path
        m = yaml.safe_load((Path("datasets/adaptive-policy-v1") / "manifest.yaml").read_text())
        assert m['holdout_count'] + m['calibration_count'] == m['scenario_count']


class TestPolicyConsistency:
    """Policy decisions must be deterministic."""

    def test_same_input_same_decision(self):
        engine = AdaptivePolicyEngine()
        d1 = engine.decide("ERROR: fail", "log")
        d2 = engine.decide("ERROR: fail", "log")
        assert d1.action == d2.action
        assert d1.level == d2.level

    def test_dry_run_matches_decide(self):
        engine = AdaptivePolicyEngine()
        budget = ContextBudget(current_tokens=100000, model_context_limit=131072)
        d1 = engine.decide("test", "log", budget)
        d2 = engine.dry_run("test", "log", budget)
        assert d1.action == d2.action
