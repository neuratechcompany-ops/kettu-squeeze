"""Session Dedup Engine — exact + normalized dedup with short refs.

Goal: ≤10 token references. Session-scoped by default.
No LLM. No embeddings. Deterministic.
"""

from __future__ import annotations

import hashlib, re, time
from dataclasses import dataclass, field
from collections import OrderedDict


@dataclass
class DedupRef:
    """Short reference: §k:A1B2C3§ — ~4 tokens."""
    hash_key: str  # first 12 hex chars of SHA-256
    original_tokens: int = 0

    def short(self) -> str:
        return f"§k:{self.hash_key[:6]}§"

    def __len__(self):
        return 4  # token estimate


class SessionDedup:
    """Session-scoped dedup with LRU eviction."""

    def __init__(self, max_entries: int = 10000, normalize: bool = True):
        self._cache: OrderedDict[str, DedupRef] = OrderedDict()
        self.max_entries = max_entries
        self.normalize = normalize
        self.hits = 0
        self.misses = 0

    def lookup(self, content: str) -> DedupRef | None:
        key = self._key(content)
        if key in self._cache:
            self._cache.move_to_end(key)
            self.hits += 1
            return self._cache[key]
        return None

    def store(self, content: str) -> DedupRef:
        key = self._key(content)
        ref = DedupRef(hash_key=key, original_tokens=len(content) // 3)
        self._cache[key] = ref
        self._cache.move_to_end(key)
        self.misses += 1
        if len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return ref

    def dedup(self, content: str) -> tuple[str, bool]:
        """Returns (output, was_deduped)."""
        existing = self.lookup(content)
        if existing:
            return existing.short(), True
        self.store(content)
        return content, False

    def _key(self, content: str) -> str:
        if self.normalize:
            content = self._normalize(content)
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    @staticmethod
    def _normalize(content: str) -> str:
        """Normalize: strip ANSI, normalize whitespace, remove temp paths."""
        c = re.sub(r'\x1b\[[0-9;]*m', '', content)  # ANSI
        c = re.sub(r'[ \t]+', ' ', c)  # whitespace
        c = re.sub(r'/tmp/[a-zA-Z0-9_/-]+', '/tmp/...', c)  # temp paths
        c = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', 'TIMESTAMP', c)  # timestamps
        c = re.sub(r'\d+\.\d+[sm]s', 'DURATION', c)  # durations
        return c.strip()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / max(total, 1)

    def clear(self):
        self._cache.clear()
        self.hits = 0
        self.misses = 0


class ModelFacingPayload:
    """Minimal payload for the model — no internal metadata."""

    def __init__(self):
        self.dedup = SessionDedup()

    def wrap(self, compressed_content: str, refs: list[str] = None,
             critical_warnings: list[str] = None) -> str:
        """Produce model-facing payload: content + minimal refs + warnings."""
        parts = [compressed_content]
        if refs:
            parts.append("│ refs: " + " ".join(refs[:5]))
        if critical_warnings:
            parts.append("│ ⚠ " + "; ".join(critical_warnings[:3]))
        return "\n".join(parts)

    def dedup_and_wrap(self, content: str, refs: list[str] = None,
                       warnings: list[str] = None) -> tuple[str, bool]:
        """Dedup + wrap in one call. Returns (payload, was_deduped)."""
        result, was_dedup = self.dedup.dedup(content)
        if was_dedup:
            return result, True
        return self.wrap(result, refs, warnings), False
