"""Execution Plan — bridges AdaptivePolicyEngine to real compression engine.

Separates decision (what) from execution (how) from result (what happened).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from kettu_squeeze.policy.models import CompressionAction, CompressionDecision, CompressionLevel


class ExecutionMode(str, Enum):
    LEGACY = "legacy"      # Current v0.1 behavior
    ADAPTIVE = "adaptive"  # Policy engine decides, engine executes
    SHADOW = "shadow"      # Legacy executes, adaptive runs in parallel


@dataclass
class CompressionExecutionPlan:
    """Concrete execution instructions derived from CompressionDecision."""
    action: CompressionAction = CompressionAction.KEEP_RAW
    level: CompressionLevel = CompressionLevel.L0
    strategy: str = "passthrough"

    target_tokens: int = 0

    # What must be preserved
    protected_fields: list[str] = field(default_factory=list)
    protected_content: list[str] = field(default_factory=list)

    # Artifact policy
    externalize_to_store: bool = False
    store_raw_reference: bool = True

    # Verification
    require_full_verification: bool = True
    require_protected_field_check: bool = False
    require_recoverability_check: bool = False
    hard_gate_on_loss: bool = False

    # Fallback
    fallback_level: Optional[CompressionLevel] = None
    fallback_strategy: Optional[str] = None
    max_fallback_attempts: int = 2

    # Metadata
    decision_id: str = ""
    policy_version: str = "0.2.0"
    reason: str = ""

    @classmethod
    def from_decision(cls, decision: CompressionDecision) -> CompressionExecutionPlan:
        """Convert policy decision to executable plan."""
        plan = cls(
            action=decision.action,
            level=decision.level,
            strategy=decision.strategy,
            target_tokens=decision.estimated_output_tokens,
            reason=decision.reason,
            policy_version=decision.policy_version,
        )

        # Set verification requirements based on level
        if decision.level == CompressionLevel.L0:
            plan.require_full_verification = False
            plan.require_recoverability_check = False
        elif decision.level == CompressionLevel.L1:
            plan.require_full_verification = True
            plan.require_recoverability_check = True
        elif decision.level == CompressionLevel.L2:
            plan.require_full_verification = True
            plan.require_protected_field_check = True
            plan.hard_gate_on_loss = True
            plan.fallback_level = CompressionLevel.L1
        elif decision.level == CompressionLevel.L3:
            plan.require_full_verification = True
            plan.require_protected_field_check = True
            plan.require_recoverability_check = True
            plan.hard_gate_on_loss = True
            plan.fallback_level = CompressionLevel.L2
            plan.externalize_to_store = True

        # Protected fields from importance
        if decision.importance:
            plan.protected_fields = decision.importance.protected_fields

        # Action-specific overrides
        if decision.action == CompressionAction.KEEP_RAW:
            plan.require_full_verification = False
            plan.strategy = "passthrough"
        elif decision.action == CompressionAction.EXTERNALIZE:
            plan.externalize_to_store = True
            plan.strategy = "externalize_only"
        elif decision.action == CompressionAction.DROP:
            # Blocked by default — requires explicit policy override
            plan.action = CompressionAction.KEEP_RAW
            plan.reason = "DROP not permitted by default policy"
            plan.strategy = "passthrough"

        return plan


@dataclass
class ExecutionReport:
    """Result of executing a CompressionExecutionPlan."""
    success: bool = True
    action_executed: CompressionAction = CompressionAction.KEEP_RAW
    level_executed: CompressionLevel = CompressionLevel.L0
    strategy_used: str = "passthrough"
    fallback_used: bool = False
    fallback_chain: list[str] = field(default_factory=list)

    input_tokens: int = 0
    output_tokens: int = 0

    compression_latency_ms: float = 0.0
    verification_passed: bool = True
    hard_gate_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    protected_fields_expected: int = 0
    protected_fields_preserved: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.input_tokens <= 0:
            return 1.0
        return self.output_tokens / self.input_tokens

    @property
    def token_savings(self) -> int:
        return max(0, self.input_tokens - self.output_tokens)

    @property
    def is_legacy(self) -> bool:
        return "legacy" in self.strategy_used or self.strategy_used == "legacy"
