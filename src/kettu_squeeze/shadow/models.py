"""Shadow mode — runs legacy + adaptive in parallel, compares results.

Shadow mode is non-blocking, isolated, safe for production path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from kettu_squeeze.policy.models import CompressionAction, CompressionDecision, CompressionLevel
from kettu_squeeze.policy.execution import ExecutionReport


class ComparisonVerdict(str):
    ADAPTIVE_WIN = "adaptive_win"
    LEGACY_WIN = "legacy_win"
    TIE = "tie"
    INVALID = "invalid_comparison"
    ADAPTIVE_FAILED = "adaptive_failed"
    LEGACY_FAILED = "legacy_failed"


@dataclass
class ShadowResult:
    """Result of a single shadow-mode comparison."""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    scenario_id: str = ""
    input_type: str = "unknown"

    # Legacy
    legacy_action: Optional[CompressionAction] = None
    legacy_level: Optional[CompressionLevel] = None
    legacy_report: Optional[ExecutionReport] = None

    # Adaptive
    adaptive_decision: Optional[CompressionDecision] = None
    adaptive_action: Optional[CompressionAction] = None
    adaptive_level: Optional[CompressionLevel] = None
    adaptive_report: Optional[ExecutionReport] = None

    # Comparison
    decision_match: bool = False
    level_match: bool = False
    action_match: bool = False

    verdict: str = ComparisonVerdict.TIE
    reason: str = ""

    # Metrics
    legacy_tokens: int = 0
    adaptive_tokens: int = 0
    legacy_latency_ms: float = 0.0
    adaptive_latency_ms: float = 0.0
    shadow_overhead_ms: float = 0.0

    legacy_hard_gates_passed: bool = True
    adaptive_hard_gates_passed: bool = True

    adaptive_error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class ShadowComparator:
    """Compares legacy and adaptive results, determines winner."""

    def compare(
        self,
        legacy: ExecutionReport,
        adaptive: ExecutionReport,
        adaptive_decision: CompressionDecision,
        scenario_id: str = "",
        input_type: str = "unknown",
    ) -> ShadowResult:
        result = ShadowResult(
            scenario_id=scenario_id,
            input_type=input_type,
            legacy_report=legacy,
            adaptive_report=adaptive,
            adaptive_decision=adaptive_decision,
            legacy_action=CompressionAction.KEEP_RAW,
            adaptive_action=adaptive_decision.action,
            legacy_level=CompressionLevel.L0,
            adaptive_level=adaptive_decision.level,
            legacy_tokens=legacy.output_tokens,
            adaptive_tokens=adaptive.output_tokens,
            legacy_latency_ms=legacy.compression_latency_ms,
            legacy_hard_gates_passed=len(legacy.hard_gate_failures) == 0,
            adaptive_hard_gates_passed=len(adaptive.hard_gate_failures) == 0,
        )

        # 1. Hard gate check — automatic loss
        if not result.adaptive_hard_gates_passed and result.legacy_hard_gates_passed:
            result.verdict = ComparisonVerdict.LEGACY_WIN
            result.reason = "Adaptive hard gate failure"
            return result
        if not result.legacy_hard_gates_passed and result.adaptive_hard_gates_passed:
            result.verdict = ComparisonVerdict.ADAPTIVE_WIN
            result.reason = "Legacy hard gate failure"
            return result
        if not result.legacy_hard_gates_passed and not result.adaptive_hard_gates_passed:
            result.verdict = ComparisonVerdict.TIE
            result.reason = "Both hard gate failures"
            return result

        # 2. Protected fields check
        adaptive_preserved = adaptive.protected_fields_preserved
        legacy_preserved = legacy.protected_fields_preserved
        if adaptive_preserved > legacy_preserved:
            result.verdict = ComparisonVerdict.ADAPTIVE_WIN
            result.reason = "Adaptive preserved more protected fields"
            return result
        if legacy_preserved > adaptive_preserved:
            result.verdict = ComparisonVerdict.LEGACY_WIN
            result.reason = "Legacy preserved more protected fields"
            return result

        # 3. Token savings check
        adaptive_savings = adaptive.token_savings
        legacy_savings = legacy.token_savings
        if adaptive_savings > legacy_savings * 1.05:  # 5% threshold
            result.verdict = ComparisonVerdict.ADAPTIVE_WIN
            result.reason = f"Adaptive saved {adaptive_savings - legacy_savings} more tokens"
            return result
        if legacy_savings > adaptive_savings * 1.05:
            result.verdict = ComparisonVerdict.LEGACY_WIN
            result.reason = f"Legacy saved {legacy_savings - adaptive_savings} more tokens"
            return result

        # 4. Adaptive KEEP_RAW when legacy compressed unnecessarily
        if adaptive_decision.action == CompressionAction.KEEP_RAW and adaptive_decision.reason:
            result.verdict = ComparisonVerdict.ADAPTIVE_WIN
            result.reason = "Adaptive correctly chose KEEP_RAW"
            return result

        # 5. Fallback used
        if adaptive.fallback_used and not legacy.fallback_used:
            result.verdict = ComparisonVerdict.LEGACY_WIN
            result.reason = "Adaptive used fallback"
            return result

        # Default: tie
        result.verdict = ComparisonVerdict.TIE
        result.decision_match = True
        result.action_match = True
        result.reason = "Equivalent results"
        return result


class ShadowConfig:
    """Configuration for shadow mode execution."""
    enabled: bool = False
    execute_adaptive: bool = True
    sample_rate: float = 1.0
    timeout_ms: int = 5000
    persist_results: bool = True
    redact_raw: bool = True

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class ShadowStorage:
    """Stores shadow comparison results."""

    def __init__(self, base_path: str = ".kettu-squeeze/shadow"):
        from pathlib import Path
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)

    def persist(self, result: ShadowResult) -> str:
        import json
        path = self.base / f"{result.run_id}.json"
        path.write_text(json.dumps({
            "run_id": result.run_id,
            "scenario_id": result.scenario_id,
            "verdict": result.verdict,
            "reason": result.reason,
            "legacy_tokens": result.legacy_tokens,
            "adaptive_tokens": result.adaptive_tokens,
            "adaptive_action": result.adaptive_action.value if result.adaptive_action else None,
            "adaptive_level": result.adaptive_level.value if result.adaptive_level else None,
            "timestamp": result.timestamp,
        }, indent=2))
        return str(path)
