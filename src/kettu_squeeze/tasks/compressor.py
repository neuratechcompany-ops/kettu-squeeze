"""v0.5.1 — Critical-Preserving Compression.

Span-level protection: extract critical facts, compress supporting context,
remove noise. Compact model-facing encoding. Deterministic. No LLM.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class FactClass(str, Enum):
    CRITICAL = "critical"
    SUPPORTING = "supporting"
    NOISE = "noise"


@dataclass
class CriticalSpan:
    text: str
    label: str  # ID, PATH, EXIT, ERR, etc.
    start: int = 0
    end: int = 0


@dataclass
class TaskAwareResult:
    critical_spans: list[CriticalSpan] = field(default_factory=list)
    critical_block: str = ""
    supporting_block: str = ""
    kept_raw: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    noise_removed: int = 0
    overprotection_rate: float = 0.0
    
    @property
    def reduction(self): return (self.input_tokens - self.output_tokens) / max(self.input_tokens, 1)
    @property
    def compressed(self): return self.critical_block + "\n" + self.supporting_block

# ── Span extractors per task type ──
CRITICAL_PATTERNS = {
    "debugging": [
        (r"(Traceback \(most recent call last\).*?)(?=\n\w)", "TRACEBACK", 200),
        (r"((?:[A-Z]\w+)?\s*Error(?::.*?)?(?=\n|$))", "ERROR", 80),
        (r'(File\s+".*?",\s*line\s*\d+)', "FILE", 80),
        (r"(exit\s*code\s*\d+)", "EXIT", 30),
    ],
    "test_fixing": [
        (r"((?:test_\w+|tests?/\S+\.py)\s+FAILED(?::.*?)?(?=\n|$))", "FAIL", 120),
        (r"(assert\s+.*?(?=\n|$))", "ASSERT", 100),
        (r"(\d+\s+passed.*?\d+\s+failed)", "SUMMARY", 50),
        (r"(exit\s*=?\s*\d+)", "EXIT", 20),
    ],
    "docker": [
        (r"(\w{12}\s.*?(?=\n|$))", "CONTAINER", 100),
        (r"(Exited\s*\(\d+\))", "STATE", 30),
        (r"(OOMKilled)", "FATAL", 20),
        (r"((?:error|Error|ERROR).*?(?=\n|$))", "ERROR", 80),
    ],
    "kubernetes": [
        (r"(\S+-\S+\s+\d+/\d+\s+(?:CrashLoopBackOff|Error|ImagePullBackOff|Failed\S*))", "POD", 100),
        (r"(OOMKilled)", "FATAL", 20),
        (r"(exit\s*code\s*\d+)", "EXIT", 30),
        (r"((?:error|Error|ERROR|Failed).*?(?=\n|$))", "ERROR", 80),
    ],
    "git": [
        (r"(diff\s+--git.*?(?=\n))", "DIFF", 80),
        (r"((?:---|\+\+\+)\s+\S+)", "FILE", 60),
        (r"((?:\+|-)def\s+\w+.*?(?=\n))", "CHANGE", 100),
        (r"(modified:\s+\S+)", "MODIFIED", 60),
    ],
    "json_api": [
        (r"(\"(?:status|code|id|message|request_id)\"\s*:\s*(?:\"[^\"]*\"|\d+))", "FIELD", 120),
        (r"(\"(?:error|errors)\"\s*:\s*\[)", "ERRORS", 60),
    ],
    "logs": [
        (r"(ERROR.*?(?=\n))", "ERROR", 80),
        (r"(FATAL.*?(?=\n))", "FATAL", 60),
        (r"(CRITICAL.*?(?=\n))", "CRITICAL", 60),
        (r"((?:Exception|Traceback).*?(?=\n))", "EXCEPTION", 80),
    ],
}

NOISE_PATTERNS = [
    r"^INFO\b",
    r"^DEBUG\b",
    r"heartbeat",
    r"^\s*$",
    r"startup complete",
    r"pip install",
    r"(?:PASSED|passed)\s*$",
    r"^\d+s\s*$",
    r"plugin.*registered",
    r"collected \d+ items",
]


def extract_critical_spans(content: str, task_type: str) -> list[CriticalSpan]:
    """Extract critical spans from content based on task type."""
    patterns = CRITICAL_PATTERNS.get(task_type, CRITICAL_PATTERNS["logs"])
    spans = []
    seen = set()
    
    for pat, label, max_len in patterns:
        for m in re.finditer(pat, content, re.MULTILINE | re.DOTALL):
            text = m.group(1)[:max_len].strip()
            if text not in seen:
                spans.append(CriticalSpan(text=text, label=label, start=m.start(), end=m.end()))
                seen.add(text)
    
    return spans


def classify_lines(content: str, task_type: str, critical_spans: list[CriticalSpan]) -> tuple[list[str], list[str], list[str]]:
    """Classify lines into critical, supporting, noise."""
    critical_set = set((s.start, s.end) for s in critical_spans)
    lines = content.split("\n")
    critical_lines = []
    supporting_lines = []
    noise_lines = []
    
    pos = 0
    for line in lines:
        line_end = pos + len(line)
        is_critical = any(start <= pos <= end or start <= line_end <= end for start, end in critical_set)
        is_noise = any(re.search(p, line, re.IGNORECASE) for p in NOISE_PATTERNS)
        
        if is_critical:
            critical_lines.append(line)
        elif is_noise and not is_critical:
            noise_lines.append(line)
        else:
            supporting_lines.append(line)
        pos = line_end + 1  # +1 for newline
    
    return critical_lines, supporting_lines, noise_lines


def compress_supporting(lines: list[str], max_lines: int = 20) -> str:
    """Compress supporting context: dedup, collapse, summarize."""
    if not lines: return ""
    
    # Dedup consecutive identical lines
    deduped = []
    for line in lines:
        if deduped and deduped[-1] == line:
            if not deduped[-1].endswith(" ×2"):
                deduped[-1] += " ×2"
            else:
                count = int(deduped[-1].split("×")[-1])
                deduped[-1] = deduped[-1].rsplit("×", 1)[0] + f"×{count+1}"
        else:
            deduped.append(line)
    
    # Truncate if too many
    if len(deduped) > max_lines:
        return "\n".join(deduped[:max_lines]) + f"\n[{len(deduped) - max_lines} more lines]"
    return "\n".join(deduped)


def compact_encode(critical_spans: list[CriticalSpan], supporting_block: str,
                   task_type: str, noise_count: int) -> str:
    """Encode result in minimal model-facing format."""
    parts = []
    
    # Critical facts — compact
    by_label = {}
    for s in critical_spans:
        by_label.setdefault(s.label, []).append(s.text)
    
    for label in ["ERROR", "FATAL", "FAIL", "EXIT", "STATE", "POD", "TRACEBACK", "FILE", "ASSERT",
                   "SUMMARY", "CONTAINER", "DIFF", "CHANGE", "MODIFIED", "FIELD", "ERRORS", "EXCEPTION", "CRITICAL"]:
        if label in by_label:
            for text in by_label[label][:5]:  # max 5 per label
                parts.append(f"{label}: {text}")
    
    # Supporting — minimal
    if supporting_block.strip():
        supp_lines = supporting_block.strip().split("\n")
        parts.append(f"CTX: {len(supp_lines)} lines")
        # Show first 3 non-empty supporting lines
        shown = 0
        for l in supp_lines:
            if l.strip() and shown < 3:
                parts.append(f"  {l[:80]}")
                shown += 1
    
    if noise_count > 0:
        parts.append(f"[{noise_count} noise lines removed]")
    
    return "\n".join(parts)


def compress_critical_preserving(content: str, task_type: str) -> TaskAwareResult:
    """Full v0.5.1 pipeline: extract → classify → compress → encode."""
    in_tok = len(content) // 3
    
    # 1. Extract critical spans
    critical_spans = extract_critical_spans(content, task_type)
    
    # 2. Classify lines
    critical_lines, supporting_lines, noise_lines = classify_lines(content, task_type, critical_spans)
    
    # 3. Compress supporting
    supporting_block = compress_supporting(supporting_lines)
    
    # 4. Compact encode
    critical_block = compact_encode(critical_spans, supporting_block, task_type, len(noise_lines))
    supporting_block = ""  # Already included in compact_encode
    
    result = TaskAwareResult(
        critical_spans=critical_spans,
        critical_block=critical_block,
        supporting_block="",  # embedded in critical_block
        kept_raw=len(critical_spans) == 0 or (len(critical_lines) + len(supporting_lines)) == 0,
        input_tokens=in_tok,
        noise_removed=len(noise_lines),
    )
    result.output_tokens = len(result.compressed) // 3
    result.overprotection_rate = (len(critical_lines) + len(supporting_lines)) / max(len(content.split("\n")), 1) if not result.kept_raw else 1.0
    return result
