"""Compression Strategy Framework — base contract, registry, dispatcher.

v0.3: Strategy-based compression. Policy selects by capability, not name.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StrategyCapability(str, Enum):
    """Capabilities a strategy can advertise. Policy selects by these, not by name."""
    LOSSLESS = "lossless"
    RECOVERABLE = "recoverable"
    HIGH_FIDELITY = "high_fidelity"
    STRUCTURED = "structured"
    SEMANTIC = "semantic"
    REPETITIVE = "repetitive"  # good at dedup/folding
    INCIDENT_AWARE = "incident_aware"  # preserves errors/exceptions
    CODE_AWARE = "code_aware"  # understands source code structure


@dataclass
class StrategyDescriptor:
    """Metadata published by each strategy for registry/dispatcher."""
    name: str
    version: str = "0.3.0"
    capabilities: list[StrategyCapability] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)  # "log", "json", "python", etc.
    supported_levels: list[str] = field(default_factory=lambda: ["L0", "L1", "L2", "L3"])
    lossless: bool = True
    recoverable: bool = True
    expected_ratio: float = 0.5  # typical compression ratio
    expected_latency_ms: float = 1.0
    priority: int = 0  # higher = preferred when multiple match


@dataclass
class CompressionEstimate:
    """Pre-compression estimate."""
    expected_ratio: float = 0.5
    expected_latency_ms: float = 1.0
    risk: float = 0.0
    recoverable: bool = True


@dataclass
class StrategyResult:
    """Result of strategy execution."""
    compressed: str = ""
    refs: list[str] = field(default_factory=list)
    original_tokens: int = 0
    compressed_tokens: int = 0
    ratio: float = 1.0
    latency_ms: float = 0.0
    verifier_passed: bool = True
    protected_fields_preserved: int = 0
    protected_fields_expected: int = 0
    explanation: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class CompressionStrategy(ABC):
    """Base contract for all compression strategies."""

    descriptor: StrategyDescriptor

    @abstractmethod
    def supports(self, content: str, source_type: str) -> bool:
        """Can this strategy handle this content?"""

    @abstractmethod
    def compress(self, content: str, level: str = "L1") -> StrategyResult:
        """Execute compression."""

    @abstractmethod
    def expand(self, ref: str, session_id: str = "") -> dict:
        """Expand a reference back to content."""

    @abstractmethod
    def verify(self, original: str, result: StrategyResult) -> bool:
        """Verify compression integrity."""

    def estimate(self, content: str, level: str = "L1") -> CompressionEstimate:
        """Pre-compression estimate."""
        return CompressionEstimate(
            expected_ratio=self.descriptor.expected_ratio,
            expected_latency_ms=self.descriptor.expected_latency_ms,
            recoverable=self.descriptor.recoverable,
        )

    def explain(self, result: StrategyResult) -> list[str]:
        """Explain what the strategy did."""
        return result.explanation

    def _token_estimate(self, text: str) -> int:
        return len(text) // 3


# ═══════════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyRegistry:
    """Auto-discovering registry of compression strategies."""

    _instance: Optional[StrategyRegistry] = None
    _strategies: dict[str, CompressionStrategy] = {}
    _by_capability: dict[StrategyCapability, list[CompressionStrategy]] = {}
    _by_format: dict[str, list[CompressionStrategy]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, strategy: CompressionStrategy) -> None:
        name = strategy.descriptor.name
        self._strategies[name] = strategy
        for cap in strategy.descriptor.capabilities:
            self._by_capability.setdefault(cap, []).append(strategy)
        for fmt in strategy.descriptor.supported_formats:
            self._by_format.setdefault(fmt, []).append(strategy)

    def get(self, name: str) -> Optional[CompressionStrategy]:
        return self._strategies.get(name)

    def by_capability(self, capability: StrategyCapability) -> list[CompressionStrategy]:
        return self._by_capability.get(capability, [])

    def by_format(self, source_type: str) -> list[CompressionStrategy]:
        return sorted(
            self._by_format.get(source_type, []),
            key=lambda s: -s.descriptor.priority,
        )

    def list_all(self) -> list[StrategyDescriptor]:
        return [s.descriptor for s in self._strategies.values()]

    @property
    def count(self) -> int:
        return len(self._strategies)


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyDispatcher:
    """Selects strategy by capability + format, not by hardcoded name."""

    def __init__(self, registry: StrategyRegistry = None):
        self.registry = registry or StrategyRegistry()

    def dispatch(
        self,
        content: str,
        source_type: str,
        required_capabilities: list[StrategyCapability] = None,
        level: str = "L1",
    ) -> Optional[CompressionStrategy]:
        """Find best strategy for this content."""
        candidates = self.registry.by_format(source_type)
        if not candidates:
            candidates = list(self.registry._strategies.values())

        # Filter by required capabilities
        if required_capabilities:
            candidates = [
                s for s in candidates
                if all(cap in s.descriptor.capabilities for cap in required_capabilities)
            ]

        # Find first that supports the content
        for strategy in candidates:
            if strategy.supports(content, source_type):
                return strategy

        return None

    def has_strategy(self, source_type: str) -> bool:
        return len(self.registry.by_format(source_type)) > 0


# Global singleton
registry = StrategyRegistry()
dispatcher = StrategyDispatcher(registry)


def register_strategy(strategy: CompressionStrategy) -> CompressionStrategy:
    """Decorator-style registration."""
    registry.register(strategy)
    return strategy
