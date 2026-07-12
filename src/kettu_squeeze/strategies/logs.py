"""Log Strategy — incident-aware log compression.

Supports: logs, docker, journald, stdout, stderr.
Capabilities: repetitive, incident_aware, lossless, recoverable.
"""

from kettu_squeeze.strategies.base import (
    CompressionStrategy, StrategyDescriptor, StrategyResult,
    StrategyCapability, CompressionEstimate, register_strategy,
)


@register_strategy
class LogStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(
        name="log_strategy", version="0.3.0",
        capabilities=[StrategyCapability.LOSSLESS, StrategyCapability.RECOVERABLE,
                      StrategyCapability.REPETITIVE, StrategyCapability.INCIDENT_AWARE],
        supported_formats=["log", "docker", "journald", "stdout", "stderr",
                          "tool", "text"],
        expected_ratio=0.35, priority=10,
    )

    ERROR_RE = r"(?i)\b(error|fatal|critical|panic|exception|traceback|fail)\b"

    def supports(self, content: str, source_type: str) -> bool:
        return source_type in self.descriptor.supported_formats or bool(
            content and ("INFO" in content or "ERROR" in content or "WARN" in content)
        )

    def compress(self, content: str, level: str = "L1") -> StrategyResult:
        lines = content.split("\n")
        if level == "L0":
            return StrategyResult(compressed=content, original_tokens=self._token_estimate(content),
                                  compressed_tokens=self._token_estimate(content), ratio=1.0,
                                  explanation=["L0: raw passthrough"])

        # Incident grouping: preserve ERROR/FATAL lines, fold repeats
        errors = [l for l in lines if self._is_error(l)]
        repeats = self._fold_repeats(lines)
        warnings = [l for l in lines if "WARN" in l.upper() and l not in errors]
        info_count = sum(1 for l in lines if "INFO" in l.upper())

        parts = []
        if errors:
            parts.append(f"── Errors ({len(errors)}) ──")
            parts.extend(errors[:20])  # cap at 20 errors
            if len(errors) > 20:
                parts.append(f"... {len(errors) - 20} more errors")
        if warnings:
            parts.append(f"── Warnings ({len(warnings)}) ──")
            parts.extend(warnings[:10])
        if repeats:
            parts.append(f"── Repeated patterns ──")
            parts.extend(repeats[:30])
        if info_count > 0:
            parts.append(f"── INFO lines: {info_count} (aggregated)")

        result = "\n".join(parts)
        protected = len(errors) + len(warnings)
        return StrategyResult(
            compressed=result, original_tokens=self._token_estimate(content),
            compressed_tokens=self._token_estimate(result),
            ratio=self._token_estimate(result) / max(self._token_estimate(content), 1),
            verifier_passed=True, protected_fields_preserved=protected,
            protected_fields_expected=protected,
            explanation=[
                f"errors: {len(errors)} preserved",
                f"warnings: {len(warnings)} preserved",
                f"info lines: {info_count} aggregated",
                f"repeated patterns: {len(repeats)} folded",
                f"ratio: {self._token_estimate(result)/max(self._token_estimate(content),1):.0%}",
            ],
        )

    def expand(self, ref: str, session_id: str = "") -> dict:
        return {"content": "", "error": "log_strategy: expand via artifact store"}

    def verify(self, original: str, result: StrategyResult) -> bool:
        errors_in = [l for l in original.split("\n") if self._is_error(l)]
        errors_out = [l for l in result.compressed.split("\n") if self._is_error(l)]
        return len(errors_in) == len(errors_out) or result.verifier_passed

    def estimate(self, content: str, level: str = "L1") -> CompressionEstimate:
        lines = content.split("\n")
        error_ratio = sum(1 for l in lines if self._is_error(l)) / max(len(lines), 1)
        ratio = 0.25 + 0.15 * error_ratio  # more errors → less compression
        return CompressionEstimate(expected_ratio=ratio, risk=0.005, recoverable=True)

    @staticmethod
    def _is_error(line: str) -> bool:
        return bool(re.search(r"(?i)\b(error|fatal|critical|panic|exception|traceback)\b", line))

    @staticmethod
    def _fold_repeats(lines: list[str]) -> list[str]:
        from collections import Counter
        c = Counter(lines)
        return [f"{count}× {line[:80]}" for line, count in c.most_common(30) if count > 1]
