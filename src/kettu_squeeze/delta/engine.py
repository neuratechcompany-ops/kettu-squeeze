"""Delta Compression Engine — base + strategies.

Replaces repeated content with base_ref + compact delta.
Only applies when delta_tokens + ref_tokens < full_compressed_tokens.
"""

from __future__ import annotations

import hashlib, re, json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeltaResult:
    base_ref: str = ""
    delta_payload: str = ""
    original_tokens: int = 0
    delta_tokens: int = 0
    savings: int = 0
    reconstructable: bool = True
    checksum: str = ""
    strategy: str = "none"

    @property
    def is_beneficial(self) -> bool:
        return self.savings > 0

    def short(self) -> str:
        if not self.base_ref:
            return self.delta_payload
        return f"{self.base_ref}\n{self.delta_payload}"


class DeltaStrategy:
    """Base for all delta strategies."""
    name: str = "base"

    def supports(self, prev: str, curr: str) -> bool:
        return False

    def create(self, prev: str, curr: str) -> DeltaResult:
        return DeltaResult(strategy=self.name)

    def apply(self, base: str, delta: str) -> str:
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# Line Delta
# ═══════════════════════════════════════════════════════════════════════════════
class LineDelta(DeltaStrategy):
    name = "line_delta"

    def supports(self, prev, curr):
        return prev != curr and abs(len(prev.split("\n")) - len(curr.split("\n"))) < len(curr.split("\n")) * 0.5

    def create(self, prev, curr):
        pl = prev.split("\n"); cl = curr.split("\n")
        added = [f"+{i}:{l}" for i, l in enumerate(cl) if l not in set(pl)]
        removed = [f"-{i}:{l}" for i, l in enumerate(pl) if l not in set(cl)]
        changed = []
        for i, (a, b) in enumerate(zip(pl, cl)):
            if a != b and a in set(cl) or b in set(pl): continue
            if a != b: changed.append(f"~{i}:{a[:40]}→{b[:40]}")

        parts = added[:20] + removed[:10] + changed[:10]
        delta = "\n".join(p for p in parts if p)
        ref = f"§k:{hashlib.sha256(prev.encode()).hexdigest()[:6]}§"
        combined = f"{ref}\n{delta}"

        return DeltaResult(
            base_ref=ref, delta_payload=delta,
            original_tokens=len(curr)//3, delta_tokens=len(combined)//3,
            savings=max(0, len(curr)//3 - len(combined)//3),
            checksum=hashlib.sha256(curr.encode()).hexdigest()[:8],
            strategy="line_delta",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Delta
# ═══════════════════════════════════════════════════════════════════════════════
class JsonDelta(DeltaStrategy):
    name = "json_delta"

    def supports(self, prev, curr):
        try: json.loads(prev); json.loads(curr); return True
        except: return False

    def create(self, prev, curr):
        try:
            p = json.loads(prev); c = json.loads(curr)
        except: return DeltaResult(strategy="json_delta")

        changes = []
        if isinstance(p, dict) and isinstance(c, dict):
            for k in set(p) | set(c):
                if k not in p: changes.append(f"+$.{k}={json.dumps(c[k])}")
                elif k not in c: changes.append(f"-$.{k}")
                elif p[k] != c[k]: changes.append(f"~$.{k}:{json.dumps(p[k])}→{json.dumps(c[k])}")

        ref = f"§k:{hashlib.sha256(prev.encode()).hexdigest()[:6]}§"
        delta = "\n".join(changes[:30])
        combined = f"{ref}\n{delta}"

        return DeltaResult(
            base_ref=ref, delta_payload=delta,
            original_tokens=len(curr)//3, delta_tokens=len(combined)//3,
            savings=max(0, len(curr)//3 - len(combined)//3),
            checksum=hashlib.sha256(curr.encode()).hexdigest()[:8],
            strategy="json_delta",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test Delta
# ═══════════════════════════════════════════════════════════════════════════════
class TestDelta(DeltaStrategy):
    name = "test_delta"

    def supports(self, prev, curr):
        return bool(re.search(r'(?i)(PASSED|FAILED)', prev)) and bool(re.search(r'(?i)(PASSED|FAILED)', curr))

    def create(self, prev, curr):
        def ext(s): return {
            "passed": int(m.group(1)) if (m := re.search(r'(\d+) passed', s)) else 0,
            "failed": int(m.group(1)) if (m := re.search(r'(\d+) failed', s)) else 0,
            "failures": [l for l in s.split("\n") if "FAIL" in l.upper()],
        }
        p = ext(prev); c = ext(curr)
        parts = [f"{p['passed']}→{c['passed']} passed, {p['failed']}→{c['failed']} failed"]
        new_fails = [f for f in c["failures"] if f not in set(p["failures"])]
        fixed_fails = [f for f in p["failures"] if f not in set(c["failures"])]
        if new_fails: parts.append("NEW FAILURES:\n" + "\n".join(f"  {f}" for f in new_fails[:10]))
        if fixed_fails: parts.append(f"FIXED: {len(fixed_fails)} failures")

        ref = f"§k:{hashlib.sha256(prev.encode()).hexdigest()[:6]}§"
        delta = "\n".join(parts)
        combined = f"{ref}\n{delta}"
        return DeltaResult(base_ref=ref, delta_payload=delta,
            original_tokens=len(curr)//3, delta_tokens=len(combined)//3,
            savings=max(0, len(curr)//3 - len(combined)//3),
            checksum=hashlib.sha256(curr.encode()).hexdigest()[:8], strategy="test_delta")


# Registry
DELTA_STRATEGIES = [LineDelta(), JsonDelta(), TestDelta()]


def create_delta(prev: str, curr: str) -> DeltaResult:
    for s in DELTA_STRATEGIES:
        if s.supports(prev, curr):
            result = s.create(prev, curr)
            if result.is_beneficial:
                return result
    return DeltaResult(delta_payload=curr, original_tokens=len(curr)//3, delta_tokens=len(curr)//3, strategy="none")
