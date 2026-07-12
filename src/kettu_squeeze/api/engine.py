"""
Kettu Squeeze — main compression engine.

Coordinates: classifier → artifact store → compressor → verifier → context ledger.
"""

from __future__ import annotations

import uuid

from kettu_squeeze.artifact_store import ArtifactStore
from kettu_squeeze.classifier import classifier
from kettu_squeeze.compressors import (
    COMPRESSORS,
    GenericCompressor,
    make_ref,
)
from kettu_squeeze.context_ledger import ContextLedger
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
    SourceType,
    VerificationResult,
    Visibility,
)
from kettu_squeeze.verifier import verifier


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

    # 2. Check mime-type based mapping
    mime_policy_key = SOURCE_TYPE_POLICY_MAP.get(classification.mime_type)
    if mime_policy_key and mime_policy_key in DEFAULT_POLICIES:
        policy = DEFAULT_POLICIES[mime_policy_key]
        if request_mode != CompressionMode.STRICT_RAW:
            return policy.model_copy(update={"mode": request_mode})
        return policy

    # 3. Source-type based fallback (aligned with _pick_compressor_name)
    if classification.source_type in (SourceType.TOOL, SourceType.COMMAND):
        key = "log"
    elif classification.source_type == SourceType.API:
        key = "json"
    else:
        key = "default"

    if key in DEFAULT_POLICIES:
        policy = DEFAULT_POLICIES[key]
        if request_mode != CompressionMode.STRICT_RAW:
            return policy.model_copy(update={"mode": request_mode})
        return policy

    return DEFAULT_POLICIES["default"].model_copy(
        update={"mode": request_mode}
    )


def _pick_compressor_name(classification: ClassificationResult) -> str:
    """Map classification to a compressor key.

    Priority: source_type > source_path > mime_type.
    """
    # 1. Source-type based priority routing
    if classification.source_type in (SourceType.TOOL, SourceType.COMMAND):
        return "log"
    if classification.source_type == SourceType.API:
        return "json"

    # 2. Path-based routing (for FILE type)
    if classification.source_path:
        path_lower = classification.source_path.lower()
        for key, policy_key in SOURCE_TYPE_POLICY_MAP.items():
            if key in path_lower:
                return policy_key

    # 3. MIME-based routing
    mime = classification.mime_type
    if mime in SOURCE_TYPE_POLICY_MAP:
        return SOURCE_TYPE_POLICY_MAP[mime]

    return "generic"


class SqueezeEngine:
    """Core compression engine — coordinates all components."""

    def __init__(self, base_dir: str = "~/.kettu-squeeze"):
        self.store = ArtifactStore(base_dir)
        self.ledger = ContextLedger(self.store.db_path)

    # ── Compress ───────────────────────────────────────────────────────

    def compress(self, request: CompressionRequest) -> CompressionResponse:
        """Full compression pipeline: classify → store → compress → verify → ledger.

        If verification fails at any point, returns the raw content.
        """
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

        # Step 4: Compress
        compressor_name = _pick_compressor_name(classification)
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

        # Collect refs from compressed output
        refs: list[str] = []
        import re
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
        )

    # ── Expand ─────────────────────────────────────────────────────────

    def expand(self, request: ExpandRequest) -> ExpandResponse | None:
        """Expand a reference back to original content."""
        import re
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
        """Estimate token count for a given text and tokenizer.

        Uses tiktoken for GPT-family tokenizers, heuristic for others.
        """
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

        # Heuristic: ~4 chars per token for English, ~2 for code
        # Conservative estimate
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
        """Explicitly register an artifact as visible to the model."""
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

    def is_visible(
        self, session_id: str, content_hash: str
    ) -> bool:
        return self.ledger.is_visible(session_id, content_hash)

    def evict(self, session_id: str, artifact_id: str) -> None:
        self.ledger.evict(session_id, artifact_id)

    def evict_all(self, session_id: str) -> None:
        self.ledger.evict_all(session_id)

    def get_context(self, session_id: str) -> list[ContextEntry]:
        return self.ledger.get_visible(session_id)
