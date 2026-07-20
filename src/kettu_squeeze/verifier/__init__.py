"""
Verifier — checks every compressed output before it reaches the agent.

Any failure → fallback to raw content. No partial/best-effort results.
"""

from __future__ import annotations

import json
import re
import uuid

from kettu_squeeze.types import (
    ArtifactRecord,
    CompressionMode,
    CompressionPolicy,
    VerificationCheck,
    VerificationResult,
)


# Ref pattern: artifact:<artifact_id> or artifact:<artifact_id>:L<start>-L<end>
_REF_RE = re.compile(
    r"artifact:([a-f0-9]{32})(?::L(\d+)-L(\d+))?"
)


class Verifier:
    """Runs sanity checks on compressed outputs."""

    def verify(
        self,
        compressed: str,
        original: str,
        artifact: ArtifactRecord,
        policy: CompressionPolicy,
    ) -> VerificationResult:
        """Run all checks on the compressed output.

        Args:
            compressed: The compressed output text.
            original: The original raw content.
            artifact: The artifact record.
            policy: The compression policy.

        Returns:
            VerificationResult with pass/fail and details.
        """
        checks: list[VerificationCheck] = []

        # 1. UTF-8 validity
        checks.append(self._check_utf8(compressed))

        # 2. Non-empty
        checks.append(self._check_non_empty(compressed))

        # 3. Refs exist (if any)
        ref_check = self._check_refs_valid(
            compressed, artifact
        )
        checks.append(ref_check)

        # 4. Exit code preserved (check for common exit code patterns)
        checks.append(self._check_exit_code(compressed, original))

        # 5. Error messages preserved
        checks.append(self._check_errors_preserved(compressed, original))

        # 6. Paths preserved
        checks.append(self._check_paths_preserved(compressed, original))

        # 7. URLs preserved
        checks.append(self._check_urls_preserved(compressed, original))

        # 8. JSON validity (if output is JSON)
        if artifact.mime_type == "application/json" or (
            compressed.strip().startswith(("{", "["))
            and original.strip().startswith(("{", "["))
        ):
            checks.append(self._check_json_valid(compressed))

        # 9. Lossy marking
        checks.append(self._check_lossy_marked(compressed, policy))

        # 10. Source code strict check
        if policy.source_type == "*" and policy.mode == CompressionMode.STRICT_RAW:
            checks.append(self._check_strict_raw(compressed, original))

        passed = all(c.passed for c in checks)
        fallback_reason = None
        warnings: list[str] = []

        if not passed:
            failed = [c.name for c in checks if not c.passed]
            fallback_reason = f"Verification failed: {', '.join(failed)}"

        return VerificationResult(
            passed=passed,
            checks=checks,
            fallback_reason=fallback_reason,
            warnings=warnings,
        )

    # ── Individual Checks ───────────────────────────────────────────────

    @staticmethod
    def _check_utf8(text: str) -> VerificationCheck:
        try:
            text.encode("utf-8")
            return VerificationCheck(
                name="utf8_validity", passed=True
            )
        except UnicodeError as e:
            return VerificationCheck(
                name="utf8_validity",
                passed=False,
                detail=str(e),
            )

    @staticmethod
    def _check_non_empty(text: str) -> VerificationCheck:
        if text.strip():
            return VerificationCheck(
                name="non_empty", passed=True
            )
        return VerificationCheck(
            name="non_empty",
            passed=False,
            detail="Compressed output is empty",
        )

    def _check_refs_valid(
        self, text: str, artifact: ArtifactRecord
    ) -> VerificationCheck:
        """Verify all refs in compressed text point to this artifact."""
        refs = _REF_RE.findall(text)
        artifact_id_short = artifact.artifact_id[:32]

        for ref_id, start_str, end_str in refs:
            if ref_id != artifact_id_short:
                return VerificationCheck(
                    name="refs_valid",
                    passed=False,
                    detail=f"Ref points to different artifact: {ref_id}",
                )
            if start_str and end_str:
                start = int(start_str)
                end = int(end_str)
                if start < 1:
                    return VerificationCheck(
                        name="refs_valid",
                        passed=False,
                        detail=f"Invalid line range: {start}-{end}",
                    )
                if start > end:
                    return VerificationCheck(
                        name="refs_valid",
                        passed=False,
                        detail=f"Reversed line range: {start}-{end}",
                    )

        return VerificationCheck(name="refs_valid", passed=True)

    @staticmethod
    def _check_exit_code(
        compressed: str, original: str
    ) -> VerificationCheck:
        """Check that exit codes aren't lost (e.g., 'exit code: 1')."""
        exit_pattern = re.compile(
            r"(?i)(exit\s*(code|status)?\s*[:=]?\s*\d+)"
        )
        orig_exits = set(exit_pattern.findall(original))
        comp_exits = set(exit_pattern.findall(compressed))

        if orig_exits and not comp_exits:
            return VerificationCheck(
                name="exit_code_preserved",
                passed=False,
                detail="Exit code present in original but missing in compressed",
            )
        return VerificationCheck(
            name="exit_code_preserved", passed=True
        )

    @staticmethod
    def _check_errors_preserved(
        compressed: str, original: str
    ) -> VerificationCheck:
        """Check that error messages aren't lost."""
        error_pattern = re.compile(
            r"(?i)\b(error|exception|traceback)\b|\[ERROR x\d+\]"
        )
        orig_errors = error_pattern.findall(original)
        comp_errors = error_pattern.findall(compressed)

        if orig_errors and not comp_errors:
            return VerificationCheck(
                name="errors_preserved",
                passed=False,
                detail="Error messages in original missing from compressed",
            )
        return VerificationCheck(
            name="errors_preserved", passed=True
        )

    @staticmethod
    def _check_paths_preserved(
        compressed: str, original: str
    ) -> VerificationCheck:
        """Check file paths survive compression."""
        path_pattern = re.compile(
            r"(?:^|\s)([/\w.-]+/[/\w.-]+\.\w{1,10})(?:\s|$)"
        )
        orig_paths = set(path_pattern.findall(original))
        # Only flag if ALL paths are missing (some may be in refs)
        if orig_paths:
            comp_paths = set(path_pattern.findall(compressed))
            missing = orig_paths - comp_paths
            if len(missing) == len(orig_paths):
                return VerificationCheck(
                    name="paths_preserved",
                    passed=False,
                    detail="All file paths missing from compressed output",
                )
        return VerificationCheck(
            name="paths_preserved", passed=True
        )

    @staticmethod
    def _check_urls_preserved(
        compressed: str, original: str
    ) -> VerificationCheck:
        """Check URLs survive compression."""
        url_pattern = re.compile(
            r"https?://[^\s<>\"']+"
        )
        orig_urls = set(url_pattern.findall(original))
        comp_urls = set(url_pattern.findall(compressed))

        missing = orig_urls - comp_urls
        if missing:
            return VerificationCheck(
                name="urls_preserved",
                passed=False,
                detail=f"Missing URLs: {missing}",
            )
        return VerificationCheck(
            name="urls_preserved", passed=True
        )

    @staticmethod
    def _check_json_valid(text: str) -> VerificationCheck:
        try:
            json.loads(text)
            return VerificationCheck(
                name="json_valid", passed=True
            )
        except json.JSONDecodeError as e:
            return VerificationCheck(
                name="json_valid",
                passed=False,
                detail=str(e),
            )

    @staticmethod
    def _check_lossy_marked(
        text: str, policy: CompressionPolicy
    ) -> VerificationCheck:
        """If lossy mode, verify omissions are marked with refs."""
        if policy.mode != CompressionMode.RECOVERABLE_LOSSY:
            return VerificationCheck(
                name="lossy_marked", passed=True
            )
        # Lossy mode: must have recoverable refs for omissions
        has_refs = bool(_REF_RE.search(text))
        has_omitted = "[omitted:" in text
        if has_omitted and not has_refs:
            return VerificationCheck(
                name="lossy_marked",
                passed=False,
                detail="Lossy omissions without recoverable refs",
            )
        return VerificationCheck(
            name="lossy_marked", passed=True
        )

    @staticmethod
    def _check_strict_raw(
        compressed: str, original: str
    ) -> VerificationCheck:
        """In STRICT_RAW mode, content must be byte-identical (after ANSI strip)."""
        # Allow ANSI stripping in strict_raw
        compressed_norm = compressed.replace("\r\n", "\n")
        original_norm = original.replace("\r\n", "\n")
        if compressed_norm != original_norm:
            # Check if only ANSI was removed
            ansi_stripped = _ANSI_RE_VERIFIER.sub("", original_norm)
            if compressed_norm != ansi_stripped:
                return VerificationCheck(
                    name="strict_raw",
                    passed=False,
                    detail="STRICT_RAW content was modified",
                )
        return VerificationCheck(
            name="strict_raw", passed=True
        )


# ANSI pattern inline to avoid circular dependency
_ANSI_RE_VERIFIER = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\].*?\x1b\\")

verifier = Verifier()
