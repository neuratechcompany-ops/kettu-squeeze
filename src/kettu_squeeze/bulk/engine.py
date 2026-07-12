"""Bulk Compaction Engine — group similar fragments, replace with compact representations.

v0.5.3: Stop line-by-line removal. Group dozens/hundreds of similar lines
into single compact entries. Net token savings through bulk operations.
"""

import re
from dataclasses import dataclass, field
from collections import defaultdict, Counter


@dataclass
class BulkGroup:
    gid: str
    gtype: str  # REPEATED_LINES, TEMPLATE, STATUS_SERIES, TEST_RESULTS, etc.
    fragments: list[str] = field(default_factory=list)
    template: str = ""
    variables: list[str] = field(default_factory=list)
    count: int = 0
    first_val: str = ""
    last_val: str = ""
    original_tokens: int = 0
    
    def compact(self) -> str:
        """Produce minimal model-facing representation."""
        if not self.fragments: return ""
        
        if self.gtype == "REPEATED_LINES":
            line = self.fragments[0].strip()
            if len(self.fragments) > 1:
                return f"{line[:80]} ×{len(self.fragments)}"
            return line
        
        if self.gtype == "TEMPLATE":
            t = self.template.replace("<*>", "…")
            vars_str = ", ".join(self.variables[:5])
            more = f" +{len(self.variables)-5}" if len(self.variables) > 5 else ""
            return f"{t} ×{self.count} [{vars_str}{more}]"
        
        if self.gtype == "STATUS_SERIES":
            return f"{self.first_val}→{self.last_val} ({self.count} steps)"
        
        if self.gtype == "TEST_RESULTS":
            return f"{self.count} passed" if "passed" in str(self.fragments[0]).lower() else f"{self.count} failed"
        
        if self.gtype == "TRACEBACK_FRAMES":
            return f"[{self.count} framework frames collapsed]"
        
        if self.gtype == "COMPACT":
            return "\n".join(f[:60] for f in self.fragments[:2]) + (f"\n[{len(self.fragments)-2} more]" if len(self.fragments) > 2 else "")
        
        return "\n".join(self.fragments[:1]) + (f" [{len(self.fragments)-1} similar]" if len(self.fragments) > 1 else "")


# ═══════════════════════════════════════════════════════════════════════════════
# Grouper
# ═══════════════════════════════════════════════════════════════════════════════
def extract_template(line: str) -> str:
    """Replace variable parts with <*> to find template. Aggressive normalization."""
    t = line
    t = re.sub(r'[a-f0-9]{8,}', '<ID>', t)  # hashes
    t = re.sub(r'[a-f0-9]{6}-[a-f0-9]{4}', '<ID>', t)  # short hashes
    t = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '<TS>', t)  # timestamps
    t = re.sub(r'\d{2}:\d{2}:\d{2}', '<TIME>', t)  # time only
    t = re.sub(r'\b\d+\.\d+\.\d+\.\d+\b', '<IP>', t)  # IPs
    t = re.sub(r'\b\d+\b', '<N>', t)  # numbers
    t = re.sub(r'port\s+\d+', 'port <N>', t)  # port
    t = re.sub(r'/\w+[/\w.\-]*', '<PATH>', t)  # paths
    t = re.sub(r'[a-zA-Z]\w*@[\w.]+', '<ID>', t)  # emails
    t = re.sub(r'line\s+\d+', 'line <N>', t, flags=re.I)  # line numbers
    return t


def group_fragments(lines: list[str], critical_facts: list[str] = None) -> list[BulkGroup]:
    """Group similar lines into bulk groups. Lines containing critical facts are kept verbatim."""
    if not lines: return []
    crit = set(c.lower() for c in (critical_facts or []))
    
    # Separate critical lines — never group these
    critical_lines = []; critical_indices = set()
    non_critical = []; non_critical_indices = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s: continue
        if any(c in s.lower() for c in crit):
            critical_lines.append(s); critical_indices.add(i)
        else:
            non_critical.append(s); non_critical_indices.append(i)
    
    groups = []
    gid = 0
    
    # Critical lines stay verbatim as a single group
    if critical_lines:
        groups.append(BulkGroup(gid=f"g{gid}", gtype="COMPACT", fragments=critical_lines, count=len(critical_lines),
                                 original_tokens=sum(len(l)//3 for l in critical_lines)))
        gid += 1
    templates = defaultdict(list)
    exact = defaultdict(list)
    status_series = []
    test_lines = []
    traceback_frames = []
    other = []
    
    for s in non_critical:
        
        tpl = extract_template(s)
        
        # Traceback frames
        if s.startswith("File ") or s.startswith("  "):
            traceback_frames.append(s)
            continue
        
        # Test results
        if re.match(r"^(test_|PASSED|FAILED|\d+ passed|\d+ failed)", s, re.I):
            test_lines.append(s)
            continue
        
        # Status series (numbers progressing)
        if re.match(r"^\d+/\d+$", s) or re.match(r"^progress \d+", s, re.I):
            status_series.append(s)
            continue
        
        # Template-based grouping
        if tpl != s:  # has variables
            templates[tpl].append(s)
        else:
            exact[s].append(s)
    
    # Build groups
    gid = 0
    for tpl, items in templates.items():
        if len(items) >= 2:
            variables = []
            for item in items:
                # Extract the variable parts
                var_match = re.findall(r'(?:<ID>|<N>|<TS>|<IP>|<PATH>)', tpl)
                parts = re.split(r'(?:<ID>|<N>|<TS>|<IP>|<PATH>)', tpl)
                if len(parts) >= 2:
                    for j in range(1, len(parts)):
                        between = item[item.find(parts[j-1])+len(parts[j-1]):]
                        end = between.find(parts[j]) if j < len(parts)-1 else len(between)
                        val = between[:end].strip()
                        if val and val not in variables and len(variables) < 10:
                            variables.append(val)
            
            groups.append(BulkGroup(
                gid=f"g{gid}", gtype="TEMPLATE", fragments=items,
                template=tpl, variables=variables, count=len(items),
                original_tokens=sum(len(l)//3 for l in items)))
            gid += 1
    
    for pattern, items in exact.items():
        if len(items) >= 3:
            groups.append(BulkGroup(
                gid=f"g{gid}", gtype="REPEATED_LINES", fragments=items,
                count=len(items), original_tokens=sum(len(l)//3 for l in items)))
            gid += 1
        else:
            other.extend(items)
    
    if status_series:
        groups.append(BulkGroup(
            gid=f"g{gid}", gtype="STATUS_SERIES", fragments=status_series,
            first_val=status_series[0], last_val=status_series[-1] if len(status_series)>1 else status_series[0],
            count=len(status_series), original_tokens=sum(len(l)//3 for l in status_series)))
        gid += 1
    
    if test_lines:
        passed = [l for l in test_lines if "PASSED" in l.upper() or "passed" in l.lower()]
        failed = [l for l in test_lines if "FAILED" in l.upper() or "failed" in l.lower()]
        if len(passed) >= 3:
            groups.append(BulkGroup(gid=f"g{gid}", gtype="TEST_RESULTS", fragments=passed, count=len(passed),
                                     original_tokens=sum(len(l)//3 for l in passed)))
            gid += 1
        if failed:
            groups.append(BulkGroup(gid=f"g{gid}", gtype="TEST_RESULTS", fragments=failed, count=0, 
                                     original_tokens=sum(len(l)//3 for l in failed)))
            gid += 1
    
    if traceback_frames and len(traceback_frames) >= 5:
        groups.append(BulkGroup(gid=f"g{gid}", gtype="TRACEBACK_FRAMES", fragments=traceback_frames,
                                 count=len(traceback_frames), original_tokens=sum(len(l)//3 for l in traceback_frames)))
        gid += 1
    elif traceback_frames:
        other.extend(traceback_frames)
    
    if other:
        groups.append(BulkGroup(gid=f"g{gid}", gtype="COMPACT", fragments=other, count=len(other),
                                 original_tokens=sum(len(l)//3 for l in other)))
    
    return groups


def bulk_compact(content: str, critical_facts: list[str]) -> str:
    """Full bulk compaction pipeline. Critical fact lines never collapsed."""
    lines = content.split("\n")
    groups = group_fragments(lines, critical_facts)
    crit = [c.lower() for c in critical_facts]
    
    compacted = []
    total_saved = 0
    
    for group in groups:
        compact = group.compact()
        compact_l = compact.lower()
        lost = [c for c in crit if c in content.lower() and c not in compact_l]
        
        compact_tokens = len(compact) // 3
        saving = group.original_tokens - compact_tokens
        
        if lost or saving < 5:
            compacted.extend(group.fragments)
        else:
            compacted.append(compact)
            total_saved += saving
    
    # Phase 2: aggressive packing on the result
    result = "\n".join(compacted)
    result = aggressive_pack(result, critical_facts)
    return result


def aggressive_pack(content: str, critical_facts: list[str]) -> str:
    """Aggressive serialization: strip verbose markers, merge adjacent groups, compact JSON/test/log."""
    crit = [c.lower() for c in critical_facts]
    lines = content.split("\n")
    result = []
    prev_compact = ""
    
    for line in lines:
        s = line.strip()
        if not s:
            if result and result[-1] != "": result.append("")
            continue
        
        # Merge adjacent "×N" markers if they share the same base
        if " ×" in s and "×" in s:
            base = s.split(" ×")[0].strip()
            mult_part = s.split("×")[-1].strip()
            if prev_compact.startswith(base + " ") and "×" in prev_compact:
                prev_mult = int(prev_compact.split("×")[-1].strip())
                try:
                    new_mult = int(mult_part)
                    result[-1] = f"{base} ×{prev_mult + new_mult}"
                    prev_compact = result[-1]
                    continue
                except: pass
        
        # Remove verbose section markers
        if s.startswith(("SECTION:", "STATUS:", "GROUP:", "---", "===")):
            continue
        
        # Compact JSON packing: strip quotes around simple values
        if s.startswith('"') and s.count('"') >= 2:
            # Try json key:value
            parts = s.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip().strip('"')
                val = parts[1].strip().strip('"').strip(',')
                if len(key) < 40 and len(val) < 100:
                    s = f"{key}={val}"
        
        # Test packing: collapse PASSED/PASSED lines
        if re.match(r"^(test_\w+\s+PASSED|PASSED|^\d+\s+passed)", s, re.I):
            if result and "PASSED" in result[-1].upper() and "×" not in result[-1]:
                result[-1] = result[-1].rsplit("PASSED", 1)[0].strip() + " PASSED ×2"
                prev_compact = result[-1]
                continue
            if result and "×" in result[-1] and "PASSED" in result[-1].upper():
                try:
                    cnt = int(result[-1].split("×")[-1].strip())
                    result[-1] = result[-1].rsplit("×", 1)[0].strip() + f" ×{cnt+1}"
                    prev_compact = result[-1]
                    continue
                except: pass
        
        # Log packing: collapse repeated single-word errors
        if re.match(r"^\w+\s*$", s) and len(s) < 30:
            if result and result[-1] == s:
                result[-1] = f"{s} ×2"
                prev_compact = result[-1]
                continue
            if result and " ×" in result[-1] and result[-1].startswith(s.split(" ×")[0]):
                try:
                    cnt = int(result[-1].split("×")[-1].strip())
                    result[-1] = f"{s} ×{cnt+1}"
                    prev_compact = result[-1]
                    continue
                except: pass
        
        # Keep line
        result.append(s)
        prev_compact = s
    
    # Remove trailing empty lines
    while result and result[-1] == "": result.pop()
    
    return "\n".join(result)


def compress_bulk_preserving(content: str, task_type: str, critical_facts: list[str]) -> dict:
    """Full v0.5.3 pipeline: bulk compaction with critical fact preservation."""
    result = bulk_compact(content, critical_facts)
    in_tok = len(content) // 3
    out_tok = len(result) // 3
    c_lower = result.lower()
    cs = sum(1 for c in critical_facts if c.lower() in c_lower) / max(len(critical_facts), 1)
    
    return {
        "compressed": result,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "reduction": (in_tok - out_tok) / max(in_tok, 1),
        "crit_survival": cs,
        "unsafe": 1 if cs < 1.0 else 0,
    }
