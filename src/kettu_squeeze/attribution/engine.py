"""Attribution Engine — v0.5.2. Fragmenter fixed: proper NOISE detection."""
import re
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


class FragmentVerdict(str, Enum):
    MUST_KEEP = "must_keep"
    SHOULD_KEEP = "should_keep"
    COMPRESSIBLE = "compressible"
    SAFE_TO_DROP = "safe_to_drop"
    UNKNOWN = "unknown"


@dataclass
class ContextFragment:
    fid: str; text: str; ftype: str; start: int=0; end: int=0; token_count: int=0
    def __post_init__(self):
        if not self.token_count: self.token_count = len(self.text)//3

@dataclass
class AttributionRecord:
    fragment: ContextFragment; verdict: FragmentVerdict = FragmentVerdict.UNKNOWN
    critical_impact: float=0.0; token_savings: int=0; reasons: list=field(default_factory=list)


NOISE_PAT = re.compile(r"^(INFO|DEBUG|heartbeat|startup|pip install|collected \d+|PASSED\s*$|\d+ passed|^\d+s\s*$)", re.I)
ERROR_PAT = re.compile(r"^(ERROR|FATAL|CRITICAL|Exception|Traceback)", re.I)
WARN_PAT  = re.compile(r"^(WARN|WARNING)", re.I)
TEST_PAT  = re.compile(r"^(test_|FAILED|\d+ passed)", re.I)
STATUS_PAT= re.compile(r"^(CONTAINER|docker |kubectl|Exited|CrashLoop|OOMKilled)", re.I)


def fragment_context(content: str, task_type: str) -> list[ContextFragment]:
    fragments = []
    for i, line in enumerate(content.split("\n")):
        s = line.strip()
        if not s: continue
        if ERROR_PAT.match(s): ft = "ERROR"
        elif WARN_PAT.match(s): ft = "WARNING"
        elif NOISE_PAT.match(s) or s in ("", "."): ft = "NOISE"
        elif TEST_PAT.match(s): ft = "TEST"
        elif STATUS_PAT.match(s): ft = "STATUS"
        elif s.startswith(("---","+++","diff ","@@","+ ","- ")) and "diff" in content.lower(): ft = "DIFF"
        elif s.startswith(("{","[")): ft = "JSON"
        else: ft = "OTHER"
        fragments.append(ContextFragment(fid=f"f{len(fragments):04d}", text=line, ftype=ft, start=i, end=i))
    return fragments


def ablate_and_measure(content: str, fragments: list[ContextFragment], critical_facts: list[str]) -> list[AttributionRecord]:
    lines = content.split("\n")
    crit = [c.lower() for c in critical_facts]
    base_crit = sum(1 for c in crit if c in content.lower()) / max(len(crit), 1)
    
    records = []
    for frag in fragments:
        kept = [l for idx, l in enumerate(lines) if idx != frag.start]
        ablated = "\n".join(kept); ab_cl = ablated.lower()
        ab_crit = sum(1 for c in crit if c in ab_cl) / max(len(crit), 1)
        crit_delta = base_crit - ab_crit

        if crit_delta > 0:
            v = FragmentVerdict.MUST_KEEP; r = f"critical fact lost: {crit_delta:.2f}"
        elif frag.ftype == "NOISE":
            v = FragmentVerdict.SAFE_TO_DROP; r = "noise pattern"
        elif frag.ftype in ("WARNING","OTHER"):
            v = FragmentVerdict.COMPRESSIBLE; r = f"compressible {frag.ftype}"
        else:
            v = FragmentVerdict.SHOULD_KEEP; r = "structural, no critical loss"
        
        records.append(AttributionRecord(fragment=frag, verdict=v, critical_impact=crit_delta,
                                          token_savings=frag.token_count, reasons=[r]))
    return records


def build_attribution_map(content: str, task_type: str, critical_facts: list[str]) -> dict:
    frags = fragment_context(content, task_type)
    recs = ablate_and_measure(content, frags, critical_facts)
    s = defaultdict(int)
    for r in recs: s[r.verdict.value] += r.fragment.token_count
    s["total"] = len(content)//3; s["fragment_count"] = len(frags)
    return {"records": recs, "summary": dict(s),
            "safe_to_drop_share": s["safe_to_drop"]/max(s["total"],1),
            "must_keep_share": s["must_keep"]/max(s["total"],1)}


def compress_attributed(content: str, task_type: str, critical_facts: list[str]) -> str:
    amap = build_attribution_map(content, task_type, critical_facts)
    lines = content.split("\n"); kept = []; dropped = 0
    for r in amap["records"]:
        if r.verdict == FragmentVerdict.SAFE_TO_DROP:
            dropped += 1
        elif r.verdict == FragmentVerdict.COMPRESSIBLE:
            kept.append(r.fragment.text[:60] + ("…" if len(r.fragment.text)>60 else ""))
        else:
            kept.append(r.fragment.text)
    result = "\n".join(kept)
    if dropped > 0: result += f"\n[{dropped} noise lines removed]"
    return result
