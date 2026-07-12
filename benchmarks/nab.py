"""
Net Agent Benefit (NAB) — comprehensive metric for compression value.

NAB =
    + Token savings (weight: 0.35)
    + Latency improvement (weight: 0.15)
    + Memory reduction (weight: 0.10)
    − Quality degradation (weight: 0.25)
    − Extra expand calls (weight: 0.10)
    − Retry count (weight: 0.05)

Positive NAB → compression helps.
Negative NAB → compression hurts despite token savings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NABStatus(str, Enum):
    BENEFICIAL = "beneficial"
    NEUTRAL = "neutral"
    DETRIMENTAL = "detrimental"
    INCOMPLETE = "incomplete"    # Quality not measured — cannot compute


@dataclass
class NABComponents:
    """Raw measurements for NAB calculation."""

    # Positive components (higher = better)
    token_savings_pct: float = 0.0         # % tokens saved (0-100)
    latency_improvement_pct: float = 0.0   # % faster (negative = slower)
    memory_reduction_pct: float = 0.0      # % context window freed
    tool_call_reduction_pct: float = 0.0   # % fewer tool calls

    # Negative components (higher = worse)
    quality_degradation_pct: float = 0.0   # % task success drop
    extra_expand_calls: int = 0            # additional expand() calls needed
    retry_count_delta: int = 0             # extra retries due to missing info

    # Metadata
    scenario: str = ""
    total_actions: int = 0
    raw_total_tokens: int = 0
    compressed_total_tokens: int = 0

    # Flags for components that require LLM agent
    quality_measured: bool = False         # True if agent actually ran


@dataclass
class NABResult:
    """Computed NAB score with breakdown."""

    score: float
    status: NABStatus

    # Weighted contributions
    token_contribution: float
    latency_contribution: float
    memory_contribution: float
    tool_call_contribution: float
    quality_penalty: float
    expand_penalty: float
    retry_penalty: float

    # Raw components
    components: NABComponents

    # Interpretation
    verdict: str = ""


# Weights (sum to 1.0)
# Updated per Phase 4 spec:
#   0.30 × token_savings + 0.15 × latency + 0.10 × memory
#   + 0.10 × tool_call_reduction
#   − 0.25 × quality_degradation − 0.05 × retry_penalty − 0.05 × expand_overhead
WEIGHTS = {
    "token_savings": 0.30,
    "latency": 0.15,
    "memory": 0.10,
    "tool_calls": 0.10,
    "quality": 0.25,
    "expands": 0.05,
    "retries": 0.05,
}

# Hard gate: quality degradation > 3% → automatic FAIL
QUALITY_HARD_GATE = 0.03


def compute_nab(components: NABComponents) -> NABResult:
    """Compute Net Agent Benefit from measured components.

    Returns UNKNOWN if quality was not measured — NAB cannot be
    computed when the most important component (agent task success) is absent.
    """
    if not components.quality_measured:
        return NABResult(
            score=0.0, status=NABStatus.INCOMPLETE,
            token_contribution=0.0, latency_contribution=0.0,
            memory_contribution=0.0, tool_call_contribution=0.0,
            quality_penalty=0.0, expand_penalty=0.0, retry_penalty=0.0,
            components=components,
            verdict="NAB INCOMPLETE: agent quality not measured. "
                    "Run A/B eval with LLM agent to populate quality_degradation_pct.")
    # Positive contributions (normalize to [0, 1])
    token_contrib = WEIGHTS["token_savings"] * (components.token_savings_pct / 100)
    latency_contrib = WEIGHTS["latency"] * max(0, components.latency_improvement_pct / 100)
    memory_contrib = WEIGHTS["memory"] * max(0, components.memory_reduction_pct / 100)
    tool_contrib = WEIGHTS["tool_calls"] * max(0, components.tool_call_reduction_pct / 100)

    # Negative contributions (normalize to [0, 1])
    quality_penalty = WEIGHTS["quality"] * (components.quality_degradation_pct / 100)

    # Hard gate: quality degradation > 3% → automatic FAIL
    hard_gate_fail = components.quality_degradation_pct > QUALITY_HARD_GATE * 100

    # Expand penalty: each expand call costs ~0.02 (capped at 1.0)
    expand_penalty = WEIGHTS["expands"] * min(1.0, components.extra_expand_calls * 0.05)

    # Retry penalty: each retry costs ~0.05 (capped at 1.0)
    retry_penalty = WEIGHTS["retries"] * min(1.0, components.retry_count_delta * 0.1)

    score = (
        token_contrib + latency_contrib + memory_contrib + tool_contrib
        - quality_penalty - expand_penalty - retry_penalty
    )

    # Status
    if hard_gate_fail:
        status = NABStatus.DETRIMENTAL  # hard gate override
    elif score > 0.1:
        status = NABStatus.BENEFICIAL
    elif score < -0.1:
        status = NABStatus.DETRIMENTAL
    else:
        status = NABStatus.NEUTRAL

    # Verdict
    verdict_parts = []
    if components.token_savings_pct > 5:
        verdict_parts.append(f"+{components.token_savings_pct:.0f}% tokens saved")
    if components.quality_degradation_pct > 1:
        verdict_parts.append(f"-{components.quality_degradation_pct:.1f}% quality drop")
    if hard_gate_fail:
        verdict_parts.append("HARD GATE FAIL: quality degradation > 3%")
    if components.extra_expand_calls > 0:
        verdict_parts.append(f"{components.extra_expand_calls} extra expands")
    if not components.quality_measured:
        verdict_parts.append("⚠ quality not measured (LLM agent required)")

    verdict = "; ".join(verdict_parts) if verdict_parts else "No significant effect"

    return NABResult(
        score=round(score, 4),
        status=status,
        token_contribution=round(token_contrib, 4),
        latency_contribution=round(latency_contrib, 4),
        memory_contribution=round(memory_contrib, 4),
        tool_call_contribution=round(tool_contrib, 4),
        quality_penalty=round(quality_penalty, 4),
        expand_penalty=round(expand_penalty, 4),
        retry_penalty=round(retry_penalty, 4),
        components=components,
        verdict=verdict,
    )


def format_nab_report(result: NABResult) -> str:
    """Human-readable NAB report."""
    lines = [
        "═══ Net Agent Benefit ═══",
        f"Score:  {result.score:+.4f}  [{result.status.value}]",
        f"Verdict: {result.verdict}",
        "",
        "Contributions:",
        f"  Token savings:    {result.token_contribution:+.4f}  "
        f"({result.components.token_savings_pct:.1f}% saved, "
        f"{result.components.raw_total_tokens}→{result.components.compressed_total_tokens} tokens)",
        f"  Latency:          {result.latency_contribution:+.4f}  "
        f"({result.components.latency_improvement_pct:+.1f}%)",
        f"  Memory:           {result.memory_contribution:+.4f}  "
        f"({result.components.memory_reduction_pct:.1f}% freed)",
        f"  Quality:          {result.quality_penalty:+.4f}  "
        f"({result.components.quality_degradation_pct:.1f}% degradation)"
        + (" [ESTIMATED — no LLM agent]" if not result.components.quality_measured else ""),
        f"  Expand calls:     {result.expand_penalty:+.4f}  "
        f"({result.components.extra_expand_calls} extra)",
        f"  Retries:          {result.retry_penalty:+.4f}  "
        f"({result.components.retry_count_delta} extra)",
        "",
        f"Scenario: {result.components.scenario}",
        f"Actions:  {result.components.total_actions}",
    ]
    return "\n".join(lines)
