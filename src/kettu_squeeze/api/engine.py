"""
Kettu Squeeze — main compression engine (v0.5.5).

Coordinates: classifier → artifact store → compressor → verifier → context ledger.

v0.5.5: Production routing with strict priority, content-based fallback,
        task detection integration, RoutingDecision model, pattern RLE.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

from kettu_squeeze.artifact_store import ArtifactStore
from kettu_squeeze.classifier import classifier
from kettu_squeeze.classifier.content_classifier import detect_content_type
from kettu_squeeze.compressors import (
    COMPRESSORS,
    GenericCompressor,
    make_ref,
)
from kettu_squeeze.context_ledger import ContextLedger
from kettu_squeeze.tasks.engine import detect_task, TaskType
from kettu_squeeze.types import (
    SOURCE_TYPE_POLICY_MAP,
    DEFAULT_POLICIES,
    ArtifactRecord,
    ClassificationResult,
    CompressionMode,
    CompressionPolicy,
    CompressionRequest,
    CompressionResponse,
    ContextEntry,
    ExpandRequest,
    ExpandResponse,
    RoutingDecision,
    SourceType,
    VerificationResult,
    Visibility,
)
from kettu_squeeze.verifier import verifier


# ── File extension → compressor key (v0.5.5) ─────────────────────────────────

_FILE_EXTENSION_MAP: dict[str, str] = {
    ".json": "json",
    ".jsonl": "json",
    ".log": "log",
    ".diff": "git_diff",
    ".patch": "git_diff",
    ".py": "source_code",
    ".rs": "source_code",
    ".js": "source_code",
    ".ts": "source_code",
    ".go": "source_code",
    ".java": "source_code",
    ".kt": "source_code",
    ".rb": "source_code",
    ".sh": "source_code",
    ".cpp": "source_code",
    ".c": "source_code",
    ".md": "source_code",
    ".txt": "log",
}


# ── Task → compressor mapping (v0.5.5) ──────────────────────────────────────

_TASK_COMPRESSOR_MAP: dict[TaskType, str] = {
    TaskType.GIT: "git_diff",
    TaskType.DOCKER: "log",
    TaskType.KUBERNETES: "log",
    TaskType.LOG_ANALYSIS: "log",
    TaskType.DEBUG: "log",
    TaskType.TEST_FIX: "test_output",
    TaskType.JSON_API: "json",
    TaskType.CODE_REVIEW: "source_code",
    TaskType.ROOT_CAUSE: "log",
    TaskType.CONFIG_EDIT: "source_code",
    TaskType.SEARCH: "generic",
    TaskType.ARCHITECTURE: "source_code",
    TaskType.GENERIC: "generic",
}


def _resolve_policy(
    classification: ClassificationResult,
    request_mode: CompressionMode,
) -> CompressionPolicy:
    """Determine which compression policy to apply."""
    # 1. Check explicit source_path-based mapping
    if classification.source_path:
        path_lower = classification.source_path.lower()
        for key, policy_key in SOURCE_TYPE_POLICY_MAP.items():
            if key in path_lower:
                if policy_key in DEFAULT_POLICIES:
                    policy = DEFAULT_POLICIES[policy_key]
                    if request_mode != CompressionMode.STRICT_RAW:
                        return policy.model_copy(
                            update={"mode": request_mode}
                        )
                    return policy

    # 2. Source-type based mapping (before MIME — more specific)
    if classification.source_type in (SourceType.TOOL, SourceType.COMMAND):
        key = "log"
    elif classification.source_type == SourceType.API:
        key = "json"
    else:
        key = None

    if key and key in DEFAULT_POLICIES:
        policy = DEFAULT_POLICIES[key]
        if request_mode != CompressionMode.STRICT_RAW:
            return policy.model_copy(update={"mode": request_mode})
        return policy

    # 3. Check mime-type based mapping
    mime_policy_key = SOURCE_TYPE_POLICY_MAP.get(classification.mime_type)
    if mime_policy_key and mime_policy_key in DEFAULT_POLICIES:
        policy = DEFAULT_POLICIES[mime_policy_key]
        if request_mode != CompressionMode.STRICT_RAW:
            return policy.model_copy(update={"mode": request_mode})
        return policy

    return DEFAULT_POLICIES["default"].model_copy(
        update={"mode": request_mode}
    )


def _pick_compressor_name(
    classification: ClassificationResult,
    explicit_compressor: Optional[str] = None,
    content: str = "",
) -> tuple[str, RoutingDecision]:
    """Pick compressor with strict routing priority (v0.5.5).

    Priority:
    1. Explicit compressor override
    2. Source type
    3. MIME type
    4. File extension
    5. Path-based match (SOURCE_TYPE_POLICY_MAP)
    6. Content classifier
    7. Task detection fallback
    8. Generic

    Returns (compressor_name, RoutingDecision).
    """
    fallbacks: list[str] = []

    # ── 1. Explicit override ──
    if explicit_compressor and explicit_compressor in COMPRESSORS:
        return explicit_compressor, RoutingDecision(
            compressor_name=explicit_compressor,
            source="explicit",
            confidence=1.0,
            matched_value=explicit_compressor,
            fallbacks_tried=fallbacks,
        )

    # ── 2. Source type ──
    if classification.source_type == SourceType.API:
        fallbacks.append("source_type:api")
        return "json", RoutingDecision(
            compressor_name="json",
            source="source_type",
            confidence=0.7,
            matched_value="api",
            fallbacks_tried=fallbacks,
        )

    if classification.source_type in (SourceType.TOOL, SourceType.COMMAND):
        fallbacks.append(f"source_type:{classification.source_type.value}")
        return "log", RoutingDecision(
            compressor_name="log",
            source="source_type",
            confidence=0.7,
            matched_value=classification.source_type.value,
            fallbacks_tried=fallbacks,
        )

    # ── 3. MIME type ──
    mime_key = SOURCE_TYPE_POLICY_MAP.get(classification.mime_type)
    if mime_key and mime_key in COMPRESSORS:
        if mime_key != "source_code" or classification.source_type == SourceType.FILE:
            return mime_key, RoutingDecision(
                compressor_name=mime_key,
                source="mime_type",
                confidence=0.8,
                matched_value=classification.mime_type,
                fallbacks_tried=list(fallbacks),
            )
    fallbacks.append(f"mime_type:{classification.mime_type}")

    # ── 4. File extension ──
    if classification.source_path:
        suffix = Path(classification.source_path).suffix.lower()
        if suffix and suffix in _FILE_EXTENSION_MAP:
            ext_key = _FILE_EXTENSION_MAP[suffix]
            if ext_key in COMPRESSORS:
                return ext_key, RoutingDecision(
                    compressor_name=ext_key,
                    source="file_extension",
                    confidence=0.9,
                    matched_value=suffix,
                    fallbacks_tried=list(fallbacks),
                )
        fallbacks.append(f"file_extension:{suffix if suffix else 'none'}")

    # ── 5. Path-based match ──
    if classification.source_path:
        path_lower = classification.source_path.lower()
        # Check non-extension keys only
        non_ext_keys = {k for k in SOURCE_TYPE_POLICY_MAP if not k.startswith(".")}
        for token in sorted(non_ext_keys, key=len, reverse=True):
            if token in path_lower and SOURCE_TYPE_POLICY_MAP[token] in COMPRESSORS:
                policy_key = SOURCE_TYPE_POLICY_MAP[token]
                # Skip generic source_code matches from dictionary keys
                if policy_key == "source_code" and token in ("python", "rust", "javascript",
                    "typescript", "go", "shell", "java", "kotlin", "c", "cpp", "ruby"):
                    continue
                return policy_key, RoutingDecision(
                    compressor_name=policy_key,
                    source="path_match",
                    confidence=0.7,
                    matched_value=token,
                    fallbacks_tried=list(fallbacks),
                )
        fallbacks.append("path_match:no_match")
    else:
        fallbacks.append("path_match:no_path")

    # ── 6. Content classifier ──
    if content:
        detected = detect_content_type(content)
        if detected and detected in COMPRESSORS:
            return detected, RoutingDecision(
                compressor_name=detected,
                source="content_classifier",
                confidence=0.8,
                matched_value=detected,
                fallbacks_tried=list(fallbacks),
            )
        fallbacks.append("content_classifier:no_match")

    # ── 7. Task detection fallback ──
    if content:
        detection = detect_task(content)
        if detection.confidence >= 0.6:
            mapped = _TASK_COMPRESSOR_MAP.get(detection.task, "generic")
            if mapped in COMPRESSORS and mapped != "generic":
                # Safety: don't pick git_diff just because task is GIT
                # unless content actually looks like a diff/patch
                if mapped == "git_diff" and not any(
                    marker in content
                    for marker in ("diff --git", "--- a/", "+++ b/", "@@ ", "index ")
                ):
                    pass  # fall through to generic
                else:
                    return mapped, RoutingDecision(
                        compressor_name=mapped,
                        source="task_detection",
                        confidence=detection.confidence,
                        matched_value=detection.task.value,
                        fallbacks_tried=list(fallbacks),
                    )
        fallbacks.append(f"task_detection:{detection.task.value}:c{detection.confidence:.2f}")

    # ── 8. Generic fallback ──
    return "generic", RoutingDecision(
        compressor_name="generic",
        source="fallback",
        confidence=0.0,
        matched_value="",
        fallbacks_tried=list(fallbacks),
    )


class SqueezeEngine:
    """Core compression engine — coordinates all components."""

    def __init__(self, base_dir: str = "~/.kettu-squeeze"):
        self.store = ArtifactStore(base_dir)
        self.ledger = ContextLedger(self.store.db_path)

    # ── Compress ───────────────────────────────────────────────────────

    def compress(self, request: CompressionRequest) -> CompressionResponse:
        """Full compression pipeline: classify → store → compress → verify → ledger."""
        # Step 1: Classify
        classification = classifier.classify(
            request.content,
            request.source_type,
            request.source_path,
        )

        # Step 2: Store raw artifact
        artifact = self.store.store(
            request.content,
            classification,
            request.session_id,
            request.agent_id,
        )

        # Step 3: Resolve policy
        policy = _resolve_policy(classification, request.mode)

        # Step 4: Pick compressor with new routing (v0.5.5)
        compressor_name, routing = _pick_compressor_name(
            classification,
            explicit_compressor=request.compressor,
            content=request.content,
        )

        compressor = COMPRESSORS.get(compressor_name, GenericCompressor())

        compressed = compressor.compress(
            request.content, artifact, policy
        )

        # Step 5: Verify
        verification = verifier.verify(
            compressed, request.content, artifact, policy
        )

        if not verification.passed:
            # Fallback to raw
            routing = RoutingDecision(
                compressor_name="generic",
                source="verification_fallback",
                confidence=0.0,
                matched_value="",
                fallbacks_tried=routing.fallbacks_tried
                + [f"verification_failed:{verification.fallback_reason}"],
            )
            compressed = request.content
            verification = VerificationResult(
                passed=True,
                checks=verification.checks,
                fallback_reason=verification.fallback_reason,
                warnings=["FALLBACK_TO_RAW: " + (verification.fallback_reason or "unknown")],
            )

        # Step 6: Register in context ledger
        original_tokens = self._estimate_tokens(
            request.content, request.tokenizer
        )
        compressed_tokens = self._estimate_tokens(
            compressed, request.tokenizer
        )

        is_lossy = policy.mode == CompressionMode.RECOVERABLE_LOSSY

        self.ledger.register(
            session_id=request.session_id,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            artifact_id=artifact.artifact_id,
            representation_id=uuid.uuid4().hex,
            content_hash=artifact.content_hash,
            visibility=Visibility.SUMMARY if is_lossy else Visibility.FULL,
            estimated_tokens=compressed_tokens,
        )

        # Collect refs
        ref_pattern = re.compile(r"artifact:[a-f0-9]{32}(?::L\d+-L\d+)?")
        refs = ref_pattern.findall(compressed)

        ratio = original_tokens / max(compressed_tokens, 1)

        return CompressionResponse(
            artifact_id=artifact.artifact_id,
            mode=policy.mode,
            lossy=is_lossy,
            recoverable=True,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=round(ratio, 2),
            content=compressed,
            refs=refs,
            verification=verification,
            routing=routing,
        )

    # ── Expand ─────────────────────────────────────────────────────────

    def expand(self, request: ExpandRequest) -> ExpandResponse | None:
        """Expand a reference back to original content."""
        ref_pattern = re.compile(
            r"artifact:([a-f0-9]{32})(?::L(\d+)-L(\d+))?"
        )
        match = ref_pattern.search(request.ref)
        if not match:
            return None

        artifact_id = match.group(1)
        record = self.store.get(artifact_id)
        if record is None:
            return None

        if match.group(2) and match.group(3):
            start = int(match.group(2))
            end = int(match.group(3))
            blob = self.store.get_range(artifact_id, start, end)
            line_range = f"L{start}-L{end}"
        else:
            blob = self.store.get_blob(artifact_id)
            line_range = None

        if blob is None:
            return None

        return ExpandResponse(
            artifact_id=artifact_id,
            content=blob.decode("utf-8"),
            line_range=line_range,
        )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str, tokenizer: str) -> int:
        """Estimate token count."""
        try:
            import tiktoken
            if tokenizer in ("gpt-oss", "gpt-4", "gpt-3.5-turbo"):
                enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text))
            if tokenizer in ("gpt-2", "gpt2"):
                enc = tiktoken.get_encoding("gpt2")
                return len(enc.encode(text))
        except ImportError:
            pass
        return len(text) // 3

    # ── Context operations ─────────────────────────────────────────────

    def register_visible(
        self,
        session_id: str,
        agent_id: str,
        conversation_id: str,
        artifact_id: str,
        content_hash: str,
        visibility: Visibility = Visibility.FULL,
        estimated_tokens: int = 0,
    ) -> ContextEntry:
        return self.ledger.register(
            session_id=session_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            representation_id=uuid.uuid4().hex,
            content_hash=content_hash,
            visibility=visibility,
            estimated_tokens=estimated_tokens,
        )

    def is_visible(self, session_id: str, content_hash: str) -> bool:
        return self.ledger.is_visible(session_id, content_hash)

    def evict(self, session_id: str, artifact_id: str) -> None:
        self.ledger.evict(session_id, artifact_id)

    def evict_all(self, session_id: str) -> None:
        self.ledger.evict_all(session_id)

    def get_context(self, session_id: str) -> list[ContextEntry]:
        return self.ledger.get_visible(session_id)
