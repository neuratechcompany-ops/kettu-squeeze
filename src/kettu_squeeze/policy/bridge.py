"""Engine Bridge — connects AdaptivePolicyEngine to SqueezeEngine.

Routes decisions through the real compression pipeline.
Supports LEGACY, ADAPTIVE, and SHADOW execution modes.
"""

from __future__ import annotations

import time
import logging
from typing import Optional

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.policy.models import CompressionDecision, ContextBudget, CompressionAction, CompressionLevel
from kettu_squeeze.policy.engine import AdaptivePolicyEngine
from kettu_squeeze.policy.execution import CompressionExecutionPlan, ExecutionReport, ExecutionMode
from kettu_squeeze.shadow.models import ShadowResult, ShadowComparator, ShadowConfig, ShadowStorage
from kettu_squeeze.types import CompressionRequest, CompressionResponse, CompressionMode, SourceType

logger = logging.getLogger(__name__)


class EngineBridge:
    """Bridge between adaptive policy engine and real compression engine."""

    def __init__(
        self,
        engine: SqueezeEngine = None,
        policy_engine: AdaptivePolicyEngine = None,
        shadow_config: ShadowConfig = None,
    ):
        self.engine = engine or SqueezeEngine()
        self.policy = policy_engine or AdaptivePolicyEngine()
        self.comparator = ShadowComparator()
        self.shadow_config = shadow_config or ShadowConfig()
        self.shadow_storage = ShadowStorage() if shadow_config and shadow_config.persist_results else None

    def compress(
        self,
        content: str,
        session_id: str = "default",
        agent_id: str = "default",
        source_type: str = "unknown",
        source_path: str = "",
        mode: ExecutionMode = ExecutionMode.LEGACY,
        context_budget: Optional[ContextBudget] = None,
    ) -> tuple[CompressionResponse, Optional[ExecutionReport], Optional[ShadowResult]]:
        """Compress with requested mode. Returns (response, report, shadow_result)."""

        if mode == ExecutionMode.LEGACY:
            return self._compress_legacy(content, session_id, agent_id, source_type, source_path)

        if mode == ExecutionMode.ADAPTIVE:
            return self._compress_adaptive(content, session_id, agent_id, source_type, source_path, context_budget)

        if mode == ExecutionMode.SHADOW:
            return self._compress_shadow(content, session_id, agent_id, source_type, source_path, context_budget)

        # Default fallback
        return self._compress_legacy(content, session_id, agent_id, source_type, source_path)

    def _compress_legacy(self, content, session_id, agent_id, source_type, source_path):
        """Execute legacy v0.1 compression."""
        request = CompressionRequest(
            content=content, session_id=session_id, agent_id=agent_id,
            source_type=self._map_source_type(source_type), source_path=source_path,
        )
        t0 = time.perf_counter()
        response = self.engine.compress(request)
        elapsed = (time.perf_counter() - t0) * 1000

        report = ExecutionReport(
            action_executed=CompressionAction.KEEP_RAW if response.original_tokens == response.compressed_tokens else CompressionAction.COMPRESS,
            strategy_used="legacy",
            input_tokens=len(content) // 3,
            output_tokens=response.compressed_tokens,
            compression_latency_ms=elapsed,
        )
        return response, report, None

    def _compress_adaptive(self, content, session_id, agent_id, source_type, source_path, budget):
        """Execute adaptive policy compression with specialized strategies."""
        import kettu_squeeze.strategies.all_strategies  # ensure registration
        t0 = time.perf_counter()

        # 1. Policy decision
        decision = self.policy.decide(content, source_type, budget)
        plan = CompressionExecutionPlan.from_decision(decision)
        policy_ms = (time.perf_counter() - t0) * 1000

        # 2. Execute
        if plan.action == CompressionAction.KEEP_RAW:
            return self._pacify_keep_raw(content, decision, plan, session_id, agent_id, source_type, source_path, policy_ms)

        # 3. Try specialized strategy via dispatcher
        t1 = time.perf_counter()
        strat_result = None
        strategy_name = plan.strategy
        from kettu_squeeze.strategies.base import dispatcher as strat_dispatcher

        strategy = strat_dispatcher.dispatch(content, source_type,
            required_capabilities=[c for c in plan.strategy.split(",") if c] if plan.strategy else None,
            level=plan.level.value)

        in_tok = len(content) // 3

        if strategy and strategy.descriptor.name != "none":
            try:
                strat_result = strategy.compress(content, plan.level.value)
                strategy_name = strategy.descriptor.name
                compress_ms = (time.perf_counter() - t1) * 1000

                # Store through regular engine
                request = CompressionRequest(
                    content=strat_result.compressed, session_id=session_id, agent_id=agent_id,
                    source_type=self._map_source_type(source_type), source_path=source_path,
                )
                response = self.engine.compress(request)

                return response, ExecutionReport(
                    action_executed=plan.action, level_executed=plan.level,
                    strategy_used=strategy_name,
                    input_tokens=in_tok, output_tokens=strat_result.compressed_tokens,
                    compression_latency_ms=policy_ms + compress_ms,
                    protected_fields_expected=strat_result.protected_fields_expected,
                    protected_fields_preserved=strat_result.protected_fields_preserved,
                    fallback_used=False,
                ), None
            except Exception:
                pass  # fall through to legacy

        # 4. Fallback: legacy engine
        return self._compress_legacy_adaptive(content, plan, in_tok, policy_ms, session_id, agent_id, source_type, source_path)

    def _compress_legacy_adaptive(self, content, plan, in_tok, policy_ms, session_id, agent_id, source_type, source_path):
        """Fallback to legacy engine when specialized strategy unavailable."""
        request = CompressionRequest(
            content=content, session_id=session_id, agent_id=agent_id,
            source_type=self._map_source_type(source_type), source_path=source_path,
        )
        t1 = time.perf_counter()
        response = self.engine.compress(request)
        compress_ms = (time.perf_counter() - t1) * 1000

        return response, ExecutionReport(
            action_executed=plan.action, level_executed=plan.level,
            strategy_used="legacy_fallback",
            input_tokens=in_tok, output_tokens=response.compressed_tokens,
            compression_latency_ms=policy_ms + compress_ms,
            fallback_used=True, fallback_chain=["specialized_unavailable", "legacy"],
        ), None

    def _compress_shadow(self, content, session_id, agent_id, source_type, source_path, budget):
        """Shadow mode: legacy executes, adaptive runs in parallel for comparison."""
        # 1. Legacy execution (primary path)
        legacy_response, legacy_report, _ = self._compress_legacy(content, session_id, agent_id, source_type, source_path)

        # 2. Adaptive execution (shadow — errors don't affect primary)
        shadow_result = None
        try:
            decision = self.policy.decide(content, source_type, budget)
            _, adaptive_report, _ = self._compress_adaptive(content, session_id, agent_id, source_type, source_path, budget)

            shadow_result = self.comparator.compare(
                legacy_report, adaptive_report, decision,
                scenario_id=f"{source_type}:{source_path}", input_type=source_type,
            )
            shadow_result.legacy_tokens = legacy_report.output_tokens
            shadow_result.adaptive_tokens = adaptive_report.output_tokens

            if self.shadow_storage:
                self.shadow_storage.persist(shadow_result)
        except Exception as e:
            logger.warning(f"Shadow comparison failed: {e}")
            shadow_result = ShadowResult(adaptive_error=str(e))

        return legacy_response, legacy_report, shadow_result

    def _pacify_keep_raw(self, content, decision, plan, session_id, agent_id, source_type, source_path, policy_ms):
        """Return raw content as response — no compression performed."""
        # Register in artifact store so it's visible
        request = CompressionRequest(
            content=content, session_id=session_id, agent_id=agent_id,
            source_type=self._map_source_type(source_type), source_path=source_path,
            mode=CompressionMode.STRICT_RAW,
        )
        response = self.engine.compress(request)

        report = ExecutionReport(
            action_executed=decision.action,
            level_executed=decision.level,
            strategy_used="passthrough",
            input_tokens=len(content) // 3,
            output_tokens=len(content) // 3,
            compression_latency_ms=policy_ms,
            fallback_used=False,
        )
        return response, report, None

    @staticmethod
    def _map_source_type(source_type: str) -> SourceType:
        mapping = {
            "log": SourceType.TOOL,
            "tool": SourceType.TOOL,
            "json": SourceType.API,
            "api": SourceType.API,
            "source_code": SourceType.FILE,
            "file": SourceType.FILE,
            "test_output": SourceType.TOOL,
            "git_diff": SourceType.TOOL,
        }
        return mapping.get(source_type, SourceType.TOOL)


def create_bridge(mode: ExecutionMode = ExecutionMode.LEGACY) -> EngineBridge:
    """Create pre-configured engine bridge."""
    return EngineBridge()
