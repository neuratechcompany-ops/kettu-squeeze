"""Adaptive Policy Engine — v0.2 decision core.

Takes: content + budget + metadata
Returns: CompressionDecision

No LLM. Deterministic. Explainable.
"""

from __future__ import annotations

import time
from typing import Optional

from kettu_squeeze.policy.models import (
    CompressionAction, CompressionDecision, CompressionLevel,
    ContextBudget, CostEstimate, PressureLevel, StrategyDescriptor,
    ImportanceResult,
)
from kettu_squeeze.policy.importance import score_content, is_protected
from kettu_squeeze.types import SourceType, CompressionMode


# ── Strategy Registry ──
STRATEGY_REGISTRY: dict[str, StrategyDescriptor] = {
    "none": StrategyDescriptor(
        name="none", input_types=[], levels=[],
        cost_factor=0.0, risk_profile=0.0,
    ),
    "passthrough": StrategyDescriptor(
        name="passthrough", input_types=["*"], levels=[CompressionLevel.L0],
        recoverable=True, cost_factor=0.0, risk_profile=0.0,
    ),
    "rle_log": StrategyDescriptor(
        name="rle_log", input_types=["log", "text", "tool"],
        levels=[CompressionLevel.L1, CompressionLevel.L2],
        recoverable=True, cost_factor=0.3, risk_profile=0.01,
    ),
    "compact_json": StrategyDescriptor(
        name="compact_json", input_types=["json", "api"],
        levels=[CompressionLevel.L1],
        recoverable=True, cost_factor=0.2, risk_profile=0.005,
    ),
    "structured_test": StrategyDescriptor(
        name="structured_test", input_types=["test_output", "tool"],
        levels=[CompressionLevel.L1, CompressionLevel.L2],
        recoverable=True, cost_factor=0.4, risk_profile=0.02,
    ),
    "diff_summary": StrategyDescriptor(
        name="diff_summary", input_types=["git_diff", "tool"],
        levels=[CompressionLevel.L1],
        recoverable=True, cost_factor=0.25, risk_profile=0.01,
    ),
    "structured_summary": StrategyDescriptor(
        name="structured_summary", input_types=["*"],
        levels=[CompressionLevel.L2, CompressionLevel.L3],
        recoverable=True, cost_factor=0.5, risk_profile=0.08,
    ),
    "externalize_only": StrategyDescriptor(
        name="externalize_only", input_types=["*"],
        levels=[CompressionLevel.L2, CompressionLevel.L3],
        recoverable=True, cost_factor=0.1, risk_profile=0.02,
    ),
}

# ── Pressure → Level mapping (configurable) ──
DEFAULT_PRESSURE_THRESHOLDS: dict[PressureLevel, float] = {
    PressureLevel.LOW: 0.0,
    PressureLevel.MODERATE: 0.50,
    PressureLevel.HIGH: 0.70,
    PressureLevel.CRITICAL: 0.85,
    PressureLevel.EMERGENCY: 0.95,
}

# ── Level configuration ──
LEVEL_CONFIG: dict[CompressionLevel, dict] = {
    CompressionLevel.L0: {"max_risk": 0.0, "target_ratio": 0.0, "description": "Raw — no changes"},
    CompressionLevel.L1: {"max_risk": 0.02, "target_ratio": 0.3, "description": "Lossless/structural"},
    CompressionLevel.L2: {"max_risk": 0.10, "target_ratio": 0.6, "description": "Conservative semantic"},
    CompressionLevel.L3: {"max_risk": 0.25, "target_ratio": 0.85, "description": "Aggressive reduction"},
}


class AdaptivePolicyEngine:
    """Core decision engine for compression policy.

    Usage:
        engine = AdaptivePolicyEngine()
        budget = ContextBudget(current_tokens=180000)
        decision = engine.decide(content, "log", budget)
    """

    def __init__(self, thresholds: dict = None, level_config: dict = None):
        self.thresholds = thresholds or DEFAULT_PRESSURE_THRESHOLDS
        self.level_config = level_config or LEVEL_CONFIG
        self.registry = STRATEGY_REGISTRY

    def decide(
        self,
        content: str,
        source_type: str = "unknown",
        budget: Optional[ContextBudget] = None,
        task_metadata: Optional[dict] = None,
    ) -> CompressionDecision:
        """Make a compression decision."""
        t0 = time.perf_counter()
        tokens_in = len(content) // 3

        # 1. Protected check — must not DROP
        protected = is_protected(content)

        # 2. Importance scoring
        importance = score_content(content, source_type)

        # 3. Budget assessment
        if budget is None:
            budget = ContextBudget(current_tokens=tokens_in)

        pressure = budget.pressure

        # 4. Decision logic
        if self._should_keep_raw(content, tokens_in, budget, importance):
            decision = self._make_keep_raw(tokens_in, importance, budget)
        elif pressure in (PressureLevel.EMERGENCY, PressureLevel.CRITICAL) and not protected:
            decision = self._make_aggressive(tokens_in, importance, budget, source_type)
        elif pressure == PressureLevel.HIGH:
            decision = self._make_moderate(tokens_in, importance, budget, source_type)
        elif pressure == PressureLevel.MODERATE:
            decision = self._make_light(tokens_in, importance, budget, source_type)
        else:
            decision = self._make_keep_raw(tokens_in, importance, budget)

        # 5. Cost estimate
        decision.cost = self._estimate_cost(decision)

        # 6. Confidence
        decision.confidence = self._confidence(decision, importance)

        decision.policy_version = "0.2.0"
        decision.importance = importance

        return decision

    def _should_keep_raw(
        self, content: str, tokens: int, budget: ContextBudget,
        importance: ImportanceResult
    ) -> bool:
        """Determine if we should skip compression entirely."""
        # Small payload
        if tokens < 500:
            return True
        # High importance + low pressure
        if importance.score >= 0.85 and budget.pressure in (PressureLevel.LOW, PressureLevel.MODERATE):
            return True
        # Critical content — never risk
        if importance.score >= 1.0:
            return True
        # Source code (strict_raw policy)
        if importance.category == "function_def":
            return True
        # Protected content under non-emergency
        if is_protected(content) and budget.pressure not in (PressureLevel.EMERGENCY, PressureLevel.CRITICAL):
            return True
        # Low savings potential
        if tokens < 1000 and budget.pressure == PressureLevel.LOW:
            return True
        return False

    def _make_keep_raw(
        self, tokens: int, importance: ImportanceResult, budget: ContextBudget
    ) -> CompressionDecision:
        return CompressionDecision(
            action=CompressionAction.KEEP_RAW,
            level=CompressionLevel.L0,
            strategy="passthrough",
            reason=f"keep_raw: importance={importance.score:.0%} pressure={budget.pressure.value}",
            input_tokens=tokens,
            estimated_output_tokens=tokens,
            preservation_risk=0.0,
            expand_probability=0.0,
        )

    def _make_light(
        self, tokens: int, importance: ImportanceResult, budget: ContextBudget, source_type: str
    ) -> CompressionDecision:
        strategy = self._select_strategy(source_type, CompressionLevel.L1)
        ratio = 0.3
        return CompressionDecision(
            action=CompressionAction.COMPRESS,
            level=CompressionLevel.L1,
            strategy=strategy,
            reason=f"light: pressure={budget.pressure.value} importance={importance.score:.0%}",
            input_tokens=tokens,
            estimated_output_tokens=int(tokens * (1 - ratio)),
            preservation_risk=0.01,
            expand_probability=0.05,
        )

    def _make_moderate(
        self, tokens: int, importance: ImportanceResult, budget: ContextBudget, source_type: str
    ) -> CompressionDecision:
        strategy = self._select_strategy(source_type, CompressionLevel.L2)
        ratio = 0.5
        risk = 0.05 if importance.score < 0.8 else 0.02
        return CompressionDecision(
            action=CompressionAction.COMPRESS,
            level=CompressionLevel.L2,
            strategy=strategy,
            reason=f"moderate: pressure={budget.pressure.value} importance={importance.score:.0%}",
            input_tokens=tokens,
            estimated_output_tokens=int(tokens * (1 - ratio)),
            preservation_risk=risk,
            expand_probability=0.15,
        )

    def _make_aggressive(
        self, tokens: int, importance: ImportanceResult, budget: ContextBudget, source_type: str
    ) -> CompressionDecision:
        strategy = self._select_strategy(source_type, CompressionLevel.L3)
        ratio = 0.75
        risk = 0.10 if importance.score < 0.7 else 0.05
        return CompressionDecision(
            action=CompressionAction.COMPRESS_AGGRESSIVE,
            level=CompressionLevel.L3,
            strategy=strategy,
            reason=f"aggressive: pressure={budget.pressure.value} importance={importance.score:.0%}",
            input_tokens=tokens,
            estimated_output_tokens=int(tokens * (1 - ratio)),
            preservation_risk=risk,
            expand_probability=0.30,
        )

    def _select_strategy(self, source_type: str, level: CompressionLevel) -> str:
        """Select best strategy for source_type at given level."""
        # Prefer strategies that match the source type
        for name, desc in self.registry.items():
            if name == "none":
                continue
            if source_type in desc.input_types and level in desc.levels:
                return name
        # Fallback to wildcard strategies
        for name, desc in self.registry.items():
            if "*" in desc.input_types and level in desc.levels:
                return name
        return "passthrough"

    def _estimate_cost(self, decision: CompressionDecision) -> CostEstimate:
        strategy = self.registry.get(decision.strategy, self.registry["passthrough"])
        return CostEstimate(
            token_savings=decision.estimated_savings,
            compression_latency_ms=decision.input_tokens * strategy.cost_factor / 100,
            expand_probability=decision.expand_probability,
            preservation_risk=decision.preservation_risk,
        )

    def _confidence(self, decision: CompressionDecision, importance: ImportanceResult) -> float:
        """Estimate confidence in the decision."""
        base = 0.95
        if importance.score >= 0.9:
            base -= 0.10  # less confident with critical data
        if decision.level == CompressionLevel.L3:
            base -= 0.10  # aggressive = less confidence
        return max(0.5, min(1.0, base))

    def dry_run(self, content: str, source_type: str = "unknown", budget: ContextBudget = None) -> CompressionDecision:
        """Return decision only, no compression performed."""
        return self.decide(content, source_type, budget)
