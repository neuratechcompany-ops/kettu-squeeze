"""Tests for Adaptive Policy Engine v0.2."""

import pytest
from kettu_squeeze.policy.models import (
    CompressionAction, CompressionDecision, CompressionLevel,
    ContextBudget, CostEstimate, PressureLevel, StrategyDescriptor,
)
from kettu_squeeze.policy.importance import score_content, is_protected
from kettu_squeeze.policy.engine import AdaptivePolicyEngine


class TestContextBudget:
    def test_empty_budget(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=0)
        assert b.pressure == PressureLevel.LOW
        assert b.available_tokens > 0

    def test_moderate_pressure(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=55000,
                          reserved_output_tokens=0, reserved_tool_tokens=0, safety_margin_tokens=0)
        assert b.pressure == PressureLevel.MODERATE

    def test_high_pressure(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=75000,
                          reserved_output_tokens=0, reserved_tool_tokens=0, safety_margin_tokens=0)
        assert b.pressure == PressureLevel.HIGH

    def test_critical_pressure(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=88000,
                          reserved_output_tokens=0, reserved_tool_tokens=0, safety_margin_tokens=0)
        assert b.pressure == PressureLevel.CRITICAL

    def test_emergency_pressure(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=97000,
                          reserved_output_tokens=0, reserved_tool_tokens=0, safety_margin_tokens=0)
        assert b.pressure == PressureLevel.EMERGENCY

    def test_target_reduction(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=110000,
                          reserved_output_tokens=0, reserved_tool_tokens=0, safety_margin_tokens=0)
        assert b.available_tokens == 0  # clamped — can't go negative
        assert b.target_reduction > 0  # deficit → need to reduce

    def test_level_for_pressure(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=97000)
        assert b.level_for_pressure() == CompressionLevel.L3

    def test_available_tokens_with_reserved(self):
        b = ContextBudget(model_context_limit=100000, current_tokens=20000,
                          reserved_output_tokens=10000, reserved_tool_tokens=5000)
        assert b.available_tokens == 100000 - 20000 - 10000 - 5000 - 16000


class TestImportanceScoring:
    def test_critical_error(self):
        r = score_content("ERROR: connection refused on port 5432", "log")
        assert r.score >= 0.9
        assert r.category == "critical_error"

    def test_traceback(self):
        r = score_content("Traceback (most recent call last):\n  File \"x.py\"", "tool")
        assert r.score >= 0.9

    def test_protected_api_key(self):
        assert is_protected("api_key: sk-abc12345defg")

    def test_security_cve(self):
        r = score_content("CVE-2026-0001: buffer overflow", "log")
        assert r.score >= 0.9

    def test_noise_low_score(self):
        r = score_content("heartbeat OK\nhealthcheck passed\n", "tool")
        assert r.score <= 0.4  # noise should be low

    def test_source_code_boost(self):
        r = score_content("print('hello')", "source_code")
        assert r.score >= 0.7

    def test_empty_content(self):
        r = score_content("", "log")
        assert r.score == 0.0

    def test_reasons_exist(self):
        r = score_content("ERROR: fail", "log")
        assert len(r.reasons) >= 1

    def test_protected_fields(self):
        r = score_content("ERROR: fail\nWARNING: minor\n", "log")
        assert len(r.protected_fields) > 0

    def test_func_def_high(self):
        r = score_content("def authenticate(token):\n    return verify(token)", "source_code")
        assert r.score >= 0.8

    def test_password_detection(self):
        assert is_protected("password: secret123")

    def test_dangerous_command(self):
        r = score_content("sudo rm -rf /", "tool")
        assert r.score >= 0.85


class TestPolicyEngine:
    @pytest.fixture
    def engine(self):
        return AdaptivePolicyEngine()

    def test_keep_raw_small_content(self, engine):
        d = engine.decide("hi", "log")
        assert d.action == CompressionAction.KEEP_RAW
        assert d.level == CompressionLevel.L0
        assert d.estimated_savings == 0

    def test_keep_raw_critical_content(self, engine):
        d = engine.decide("ERROR: CVE-2026-0001 critical vulnerability in auth", "log")
        assert d.action == CompressionAction.KEEP_RAW

    def test_keep_raw_protected(self, engine):
        d = engine.decide("api_key: sk-1234567890abcdef", "config")
        assert d.action == CompressionAction.KEEP_RAW

    def test_keep_raw_source_code(self, engine):
        d = engine.decide("def authenticate(user, pw): return True", "source_code")
        assert d.action == CompressionAction.KEEP_RAW

    def test_compress_under_pressure(self, engine):
        budget = ContextBudget(current_tokens=180000, model_context_limit=200000)
        content = "ERROR: fail\n" * 500  # moderate content
        d = engine.decide(content, "log", budget)
        assert d.action in (CompressionAction.COMPRESS, CompressionAction.COMPRESS_AGGRESSIVE)

    def test_explain_output(self, engine):
        d = engine.decide("ERROR: timeout\n" * 100, "log",
                          ContextBudget(current_tokens=190000, model_context_limit=200000))
        lines = d.explain()
        assert any("Action:" in l for l in lines)
        assert any("Level:" in l for l in lines)
        assert any("Risk:" in l for l in lines)

    def test_importance_attached(self, engine):
        d = engine.decide("ERROR: fail", "log")
        assert d.importance is not None
        assert d.importance.score >= 0.9

    def test_cost_attached(self, engine):
        d = engine.decide("some noise\n" * 200, "log")
        assert d.cost is not None

    def test_dry_run_same_as_decide(self, engine):
        d1 = engine.decide("test content", "log")
        d2 = engine.dry_run("test content", "log")
        assert d1.action == d2.action
        assert d1.level == d2.level

    def test_strategy_selected(self, engine):
        d = engine.decide("INFO: ok\n" * 200, "log",
                          ContextBudget(current_tokens=190000, model_context_limit=200000))
        assert d.strategy != "passthrough"

    def test_confidence_reasonable(self, engine):
        d = engine.decide("test", "log")
        assert 0.5 <= d.confidence <= 1.0

    def test_budget_unaware_keep_raw(self, engine):
        """Without budget, keep raw for small content."""
        d = engine.decide("small", "log")
        assert d.action == CompressionAction.KEEP_RAW

    def test_emergency_compresses_even_important(self, engine):
        """Under emergency, even important content may be compressed."""
        budget = ContextBudget(current_tokens=250000, model_context_limit=262144)
        content = "WARNING: disk usage at 95%\n" * 100
        d = engine.decide(content, "log", budget)
        assert d.action != CompressionAction.KEEP_RAW


class TestCompressionDecision:
    def test_savings_calculation(self):
        d = CompressionDecision(input_tokens=1000, estimated_output_tokens=300)
        assert d.estimated_savings == 700
        assert d.savings_ratio == 0.7

    def test_serialization(self):
        d = CompressionDecision(input_tokens=100, estimated_output_tokens=50)
        d.explain()


class TestCostEstimate:
    def test_worthwhile_savings(self):
        c = CostEstimate(token_savings=500)
        assert c.worthwhile

    def test_not_worthwhile(self):
        c = CostEstimate(token_savings=50)
        assert not c.worthwhile


class TestStrategyDescriptor:
    def test_registry_entry(self):
        d = StrategyDescriptor(name="test", input_types=["log"], cost_factor=0.5)
        assert d.name == "test"
        assert d.cost_factor == 0.5
