"""Adaptive Policy Engine — core models for Kettu Squeeze v0.2.

CompressionDecision, ContextBudget, PressureLevel, ImportanceResult,
StrategyDescriptor, CostEstimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PressureLevel(str, Enum):
    LOW = "low"            # 0-50% — plenty of room
    MODERATE = "moderate"  # 50-70% — start optimizing
    HIGH = "high"          # 70-85% — significant pressure
    CRITICAL = "critical"  # 85-95% — aggressive needed
    EMERGENCY = "emergency"  # 95%+ — drop non-critical


class CompressionAction(str, Enum):
    KEEP_RAW = "keep_raw"
    COMPRESS = "compress"
    COMPRESS_AGGRESSIVE = "compress_aggressive"
    SUMMARIZE_STRUCTURED = "summarize_structured"
    EXTERNALIZE = "externalize"
    DROP = "drop"  # forbidden for protected content


class CompressionLevel(str, Enum):
    L0 = "L0"  # Raw — no changes
    L1 = "L1"  # Lossless/structural — dedup, normalize, externalize large blobs
    L2 = "L2"  # Conservative semantic — summaries, merge repeats, keep critical
    L3 = "L3"  # Aggressive — drop non-critical, strong aggregation


@dataclass
class ContextBudget:
    """Tracks context window utilization and pressure."""
    model_context_limit: int = 262144
    current_tokens: int = 0
    reserved_output_tokens: int = 12000
    reserved_tool_tokens: int = 8000
    safety_margin_tokens: int = 16000

    @property
    def used_tokens(self) -> int:
        return self.current_tokens + self.reserved_output_tokens + self.reserved_tool_tokens

    @property
    def available_tokens(self) -> int:
        return max(0, self.model_context_limit - self.used_tokens - self.safety_margin_tokens)

    @property
    def pressure_ratio(self) -> float:
        if self.model_context_limit <= 0:
            return 0.0
        return self.used_tokens / self.model_context_limit

    @property
    def pressure(self) -> PressureLevel:
        r = self.pressure_ratio
        if r >= 0.95:
            return PressureLevel.EMERGENCY
        if r >= 0.85:
            return PressureLevel.CRITICAL
        if r >= 0.70:
            return PressureLevel.HIGH
        if r >= 0.50:
            return PressureLevel.MODERATE
        return PressureLevel.LOW

    def level_for_pressure(self) -> CompressionLevel:
        p = self.pressure
        if p == PressureLevel.EMERGENCY:
            return CompressionLevel.L3
        if p == PressureLevel.CRITICAL:
            return CompressionLevel.L2
        if p == PressureLevel.HIGH:
            return CompressionLevel.L1
        if p == PressureLevel.MODERATE:
            return CompressionLevel.L1
        return CompressionLevel.L0

    @property
    def deficit_tokens(self) -> int:
        """Actual deficit (unclamped)."""
        raw = self.model_context_limit - self.used_tokens - self.safety_margin_tokens
        return max(0, -raw)

    @property
    def target_reduction(self) -> float:
        """How much we need to reduce (0.0 = none, 1.0 = all)."""
        deficit = self.deficit_tokens
        if deficit <= 0:
            return 0.0
        return min(1.0, deficit / max(self.current_tokens, 1))


@dataclass
class ImportanceResult:
    """Deterministic importance scoring — no LLM."""
    score: float  # 0.0 = noise, 1.0 = critical
    category: str  # "critical_error", "log_noise", "source_code", etc.
    protected_fields: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class CostEstimate:
    """Estimated cost of compression decision."""
    token_savings: int = 0
    compression_latency_ms: float = 0.0
    expand_latency_ms: float = 50.0  # typical expand cost
    expand_probability: float = 0.1
    preservation_risk: float = 0.0  # 0.0 = safe, 1.0 = guaranteed loss

    @property
    def expected_value(self) -> float:
        """Expected net benefit in token-equivalents."""
        savings = self.token_savings
        expand_cost = self.expand_probability * self.expand_latency_ms / 10  # ~2 tokens/ms
        risk_cost = self.preservation_risk * 500  # penalty for critical loss
        return savings - expand_cost - risk_cost

    @property
    def worthwhile(self) -> bool:
        return self.expected_value > 100  # need at least ~100 token benefit


@dataclass
class CompressionDecision:
    """Output of the Adaptive Policy Engine."""
    action: CompressionAction = CompressionAction.KEEP_RAW
    level: CompressionLevel = CompressionLevel.L0
    strategy: str = "none"
    reason: str = "default_keep_raw"

    input_tokens: int = 0
    target_tokens: int = 0
    estimated_output_tokens: int = 0

    preservation_risk: float = 0.0
    expand_probability: float = 0.0
    confidence: float = 1.0

    cost: Optional[CostEstimate] = None
    importance: Optional[ImportanceResult] = None
    policy_version: str = "0.2.0"

    @property
    def estimated_savings(self) -> int:
        return max(0, self.input_tokens - self.estimated_output_tokens)

    @property
    def savings_ratio(self) -> float:
        if self.input_tokens <= 0:
            return 0.0
        return self.estimated_savings / self.input_tokens

    def explain(self) -> list[str]:
        lines = [
            f"Action: {self.action.value}",
            f"Level: {self.level.value}",
            f"Strategy: {self.strategy}",
            f"Reason: {self.reason}",
            f"Tokens: {self.input_tokens} → ~{self.estimated_output_tokens} (save {self.estimated_savings}, {self.savings_ratio:.0%})",
            f"Risk: {self.preservation_risk:.0%}",
            f"Expand probability: {self.expand_probability:.0%}",
            f"Confidence: {self.confidence:.0%}",
        ]
        if self.importance:
            lines.append(f"Importance: {self.importance.score:.0%} ({self.importance.category})")
            if self.importance.protected_fields:
                lines.append(f"Protected: {', '.join(self.importance.protected_fields[:5])}")
        if self.cost:
            lines.append(f"Expected value: {self.cost.expected_value:.0f} token-equiv")
        return lines


@dataclass
class StrategyDescriptor:
    """Registered compression strategy."""
    name: str
    input_types: list[str] = field(default_factory=list)
    levels: list[CompressionLevel] = field(default_factory=list)
    recoverable: bool = True
    deterministic: bool = True
    cost_factor: float = 1.0  # relative latency multiplier
    risk_profile: float = 0.0  # base preservation risk
