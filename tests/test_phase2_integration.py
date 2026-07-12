"""Phase 2 integration tests — execution plan, shadow mode, engine integration."""

import pytest
from kettu_squeeze.policy.models import (
    CompressionAction, CompressionDecision, CompressionLevel,
    ContextBudget, ImportanceResult,
)
from kettu_squeeze.policy.engine import AdaptivePolicyEngine
from kettu_squeeze.policy.execution import (
    CompressionExecutionPlan, ExecutionReport, ExecutionMode,
)
from kettu_squeeze.shadow.models import (
    ShadowResult, ShadowComparator, ShadowConfig, ShadowStorage, ComparisonVerdict,
)


class TestExecutionPlan:
    def test_from_keep_raw_decision(self):
        d = CompressionDecision(action=CompressionAction.KEEP_RAW, level=CompressionLevel.L0)
        plan = CompressionExecutionPlan.from_decision(d)
        assert plan.action == CompressionAction.KEEP_RAW
        assert plan.strategy == "passthrough"
        assert not plan.require_full_verification

    def test_from_compress_decision(self):
        d = CompressionDecision(
            action=CompressionAction.COMPRESS, level=CompressionLevel.L1,
            estimated_output_tokens=500,
        )
        plan = CompressionExecutionPlan.from_decision(d)
        assert plan.action == CompressionAction.COMPRESS
        assert plan.level == CompressionLevel.L1
        assert plan.require_recoverability_check

    def test_l2_has_fallback(self):
        d = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2)
        plan = CompressionExecutionPlan.from_decision(d)
        assert plan.fallback_level == CompressionLevel.L1
        assert plan.hard_gate_on_loss

    def test_l3_externalizes(self):
        d = CompressionDecision(action=CompressionAction.COMPRESS_AGGRESSIVE, level=CompressionLevel.L3)
        plan = CompressionExecutionPlan.from_decision(d)
        assert plan.externalize_to_store
        assert plan.fallback_level == CompressionLevel.L2

    def test_protected_fields_copied(self):
        imp = ImportanceResult(score=0.9, category="error", protected_fields=["secret"])
        d = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2,
                                importance=imp)
        plan = CompressionExecutionPlan.from_decision(d)
        assert "secret" in plan.protected_fields

    def test_drop_blocked(self):
        d = CompressionDecision(action=CompressionAction.DROP, level=CompressionLevel.L3)
        plan = CompressionExecutionPlan.from_decision(d)
        assert plan.action == CompressionAction.KEEP_RAW

    def test_externalize_action(self):
        d = CompressionDecision(action=CompressionAction.EXTERNALIZE, level=CompressionLevel.L2)
        plan = CompressionExecutionPlan.from_decision(d)
        assert plan.externalize_to_store


class TestExecutionReport:
    def test_report_fields(self):
        r = ExecutionReport(input_tokens=1000, output_tokens=300)
        assert r.token_savings == 700
        assert r.compression_ratio == 0.3

    def test_fallback_chain(self):
        r = ExecutionReport(fallback_used=True, fallback_chain=["L2", "L1"])
        assert r.fallback_used
        assert len(r.fallback_chain) == 2

    def test_hard_gate_failures(self):
        r = ExecutionReport(hard_gate_failures=["broken_ref"])
        assert len(r.hard_gate_failures) == 1


class TestShadowComparator:
    @pytest.fixture
    def comparator(self):
        return ShadowComparator()

    def test_adaptive_hard_gate_failure(self, comparator):
        legacy = ExecutionReport(input_tokens=1000, output_tokens=500)
        adaptive = ExecutionReport(input_tokens=1000, output_tokens=300,
                                    hard_gate_failures=["broken_ref"])
        decision = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2)
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict == ComparisonVerdict.LEGACY_WIN

    def test_adaptive_saves_more(self, comparator):
        legacy = ExecutionReport(input_tokens=1000, output_tokens=800)
        adaptive = ExecutionReport(input_tokens=1000, output_tokens=500)
        decision = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L2)
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict == ComparisonVerdict.ADAPTIVE_WIN

    def test_tie_when_equivalent(self, comparator):
        legacy = ExecutionReport(input_tokens=1000, output_tokens=500)
        adaptive = ExecutionReport(input_tokens=1000, output_tokens=500)
        decision = CompressionDecision(action=CompressionAction.COMPRESS, level=CompressionLevel.L1)
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict == ComparisonVerdict.TIE

    def test_keep_raw_wins_over_unnecessary_compress(self, comparator):
        legacy = ExecutionReport(input_tokens=500, output_tokens=500)  # compressed but same
        adaptive = ExecutionReport(input_tokens=500, output_tokens=500)
        decision = CompressionDecision(action=CompressionAction.KEEP_RAW, level=CompressionLevel.L0,
                                       reason="small payload")
        result = comparator.compare(legacy, adaptive, decision)
        assert result.verdict == ComparisonVerdict.ADAPTIVE_WIN


class TestShadowStorage:
    def test_persist_and_read(self, tmp_path):
        storage = ShadowStorage(str(tmp_path))
        result = ShadowResult(scenario_id="test-1", verdict=ComparisonVerdict.TIE)
        path = storage.persist(result)
        assert "test-1" in open(path).read()


class TestExecutionModes:
    def test_legacy_mode_exists(self):
        assert ExecutionMode.LEGACY.value == "legacy"

    def test_adaptive_mode_exists(self):
        assert ExecutionMode.ADAPTIVE.value == "adaptive"

    def test_shadow_mode_exists(self):
        assert ExecutionMode.SHADOW.value == "shadow"


class TestEngineIntegration:
    """Test that adaptive policy decisions work with real engine."""
    
    def test_adaptive_engine_on_log(self):
        engine = AdaptivePolicyEngine()
        content = "WARNING: minor issue\nINFO: processing\n" * 50
        budget = ContextBudget(current_tokens=180000, model_context_limit=200000)
        decision = engine.decide(content, "log", budget)
        plan = CompressionExecutionPlan.from_decision(decision)
        assert plan.action in (CompressionAction.COMPRESS, CompressionAction.COMPRESS_AGGRESSIVE)

    def test_keep_raw_for_source_code(self):
        engine = AdaptivePolicyEngine()
        content = "def authenticate(token):\n    if not token:\n        raise AuthError()\n    return verify(token)\n"
        decision = engine.decide(content, "source_code")
        plan = CompressionExecutionPlan.from_decision(decision)
        assert plan.action == CompressionAction.KEEP_RAW

    def test_level_escalates_with_pressure(self):
        engine = AdaptivePolicyEngine()
        content = "INFO: ok\n" * 500
        low_budget = ContextBudget(current_tokens=50000, model_context_limit=200000)
        high_budget = ContextBudget(current_tokens=190000, model_context_limit=200000)
        low_d = engine.decide(content, "log", low_budget)
        high_d = engine.decide(content, "log", high_budget)
        # Higher pressure → equal or higher level
        assert low_d.level.value <= high_d.level.value

    def test_importance_preserved_in_plan(self):
        engine = AdaptivePolicyEngine()
        decision = engine.decide("api_key: sk-1234567890abcdef\nERROR: fail", "config")
        plan = CompressionExecutionPlan.from_decision(decision)
        assert len(plan.protected_fields) > 0


class TestBudgetIntegration:
    def test_realistic_budget_deepseek(self):
        """Simulate DeepSeek v4 Pro 128K context."""
        budget = ContextBudget(model_context_limit=131072, current_tokens=100000)
        assert budget.pressure.value in ("high", "critical")

    def test_realistic_budget_gptoss(self):
        """Simulate GPT-OSS 120B 32K context."""
        budget = ContextBudget(model_context_limit=32768, current_tokens=28000)
        assert budget.pressure.value in ("critical", "emergency")
