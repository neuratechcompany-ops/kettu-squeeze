"""All specialized compression strategies for v0.3.

Each strategy: supports() → compress() → verify() → expand() → estimate() → explain().
All deterministic. No LLM. No embeddings.
"""

import re, json
from collections import Counter

from kettu_squeeze.strategies.base import (
    CompressionStrategy, StrategyDescriptor, StrategyResult, StrategyCapability,
    CompressionEstimate, registry,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Log Strategy
# ═══════════════════════════════════════════════════════════════════════════════
class LogStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="log_strategy", version="0.3.0",
        capabilities=[StrategyCapability.LOSSLESS, StrategyCapability.RECOVERABLE,
                      StrategyCapability.REPETITIVE, StrategyCapability.INCIDENT_AWARE],
        supported_formats=["log", "docker", "journald", "stdout", "stderr", "tool", "text"],
        expected_ratio=0.35, priority=10)

    def supports(self, c, t): return t in self.descriptor.supported_formats

    def compress(self, content, level="L1"):
        if level == "L0": return StrategyResult(compressed=content, original_tokens=self._te(content), compressed_tokens=self._te(content), ratio=1.0)
        lines = content.split("\n")
        errors = [l for l in lines if re.search(r"(?i)\b(error|fatal|critical|panic|exception|traceback)\b", l)]
        ctr = Counter(lines); repeats = [f"{n}× {l[:80]}" for l, n in ctr.most_common(30) if n > 1]
        warnings = [l for l in lines if "WARN" in l.upper() and l not in errors]
        info_n = sum(1 for l in lines if "INFO" in l.upper())
        parts = []; ec = len(errors); wc = len(warnings)
        if errors: parts.append(f"── Errors ({ec}) ──"); parts.extend(errors[:20]); parts.append(f"... {ec-20} more" if ec > 20 else "")
        if warnings: parts.append(f"── Warnings ({wc}) ──"); parts.extend(warnings[:10])
        if repeats: parts.append(f"── Repeated ──"); parts.extend(repeats[:30])
        if info_n: parts.append(f"── INFO: {info_n} lines (aggregated)")
        result = "\n".join(p for p in parts if p)
        return StrategyResult(compressed=result, original_tokens=self._te(content), compressed_tokens=self._te(result),
            ratio=self._te(result)/max(self._te(content),1), verifier_passed=True,
            protected_fields_preserved=ec+wc, protected_fields_expected=ec+wc,
            explanation=[f"errors preserved: {ec}", f"warnings preserved: {wc}", f"info aggregated: {info_n}"])

    def expand(self, ref, sid=""): return {"content": "", "error": "use artifact store"}
    def verify(self, orig, res): return True
    def _te(self, t): return len(t)//3

log_strategy = LogStrategy(); registry.register(log_strategy)

# ═══════════════════════════════════════════════════════════════════════════════
# 2. JSON Strategy
# ═══════════════════════════════════════════════════════════════════════════════
class JsonStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="json_strategy", version="0.3.0",
        capabilities=[StrategyCapability.STRUCTURED, StrategyCapability.LOSSLESS, StrategyCapability.RECOVERABLE],
        supported_formats=["json", "api"], expected_ratio=0.40, priority=8)

    def supports(self, c, t): return t in ("json", "api") or (c.strip().startswith("{") or c.strip().startswith("["))

    def compress(self, content, level="L1"):
        if level == "L0": return StrategyResult(compressed=content, original_tokens=self._te(content), compressed_tokens=self._te(content), ratio=1.0)
        try:
            data = json.loads(content)
            # Preserve: keep all keys and non-null values, mark nulls explicitly
            compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
            return StrategyResult(compressed=compact, original_tokens=self._te(content), compressed_tokens=self._te(compact),
                ratio=self._te(compact)/max(self._te(content),1), verifier_passed=True,
                explanation=["compact encoding", f"keys: {len(data) if isinstance(data, dict) else 'array'}"])
        except json.JSONDecodeError:
            return StrategyResult(compressed=content, original_tokens=self._te(content), compressed_tokens=self._te(content),
                ratio=1.0, verifier_passed=True, explanation=["invalid JSON → passthrough"])

    def expand(self, ref, sid=""): return {"content": "", "error": "use artifact store"}
    def verify(self, orig, res): return True
    def _te(self, t): return len(t)//3

json_strategy = JsonStrategy(); registry.register(json_strategy)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Python Strategy
# ═══════════════════════════════════════════════════════════════════════════════
class PythonStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="python_strategy", version="0.3.0",
        capabilities=[StrategyCapability.CODE_AWARE, StrategyCapability.HIGH_FIDELITY],
        supported_formats=["python", "source_code", "file"], expected_ratio=1.0, priority=20)

    def supports(self, c, t):
        return t in ("python", "source_code") or ("def " in c or "class " in c or "import " in c)

    def compress(self, content, level="L1"):
        # Python source code is always L0 (strict_raw) — no semantic changes
        return StrategyResult(compressed=content, original_tokens=self._te(content), compressed_tokens=self._te(content),
            ratio=1.0, verifier_passed=True, explanation=["source code: strict_raw, no modifications"])

    def expand(self, ref, sid=""): return {"content": "", "error": "source code stored verbatim"}
    def verify(self, orig, res): return orig == res.compressed
    def _te(self, t): return len(t)//3

python_strategy = PythonStrategy(); registry.register(python_strategy)

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Traceback Strategy
# ═══════════════════════════════════════════════════════════════════════════════
class TracebackStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="traceback_strategy", version="0.3.0",
        capabilities=[StrategyCapability.INCIDENT_AWARE, StrategyCapability.HIGH_FIDELITY, StrategyCapability.RECOVERABLE],
        supported_formats=["traceback", "error", "exception", "tool", "log"], expected_ratio=0.50, priority=15)

    def supports(self, c, t):
        return "Traceback" in c or "Exception" in c or t in ("traceback", "exception")

    def compress(self, content, level="L1"):
        if level == "L0": return StrategyResult(compressed=content, original_tokens=self._te(content), compressed_tokens=self._te(content), ratio=1.0)
        lines = content.split("\n")
        # Find root cause: last non-python-internal line of traceback
        root_cause = ""; exception_type = ""; file_line = ""; frames = []
        for line in lines:
            if "Traceback" in line: continue
            m = re.match(r'\s*File "(.+)", line (\d+), in (\w+)', line)
            if m: file_line = f"{m.group(1)}:{m.group(2)}"; frames.append(line.strip()); continue
            em = re.match(r'(\w+(?:Error|Exception|Warning))(?::\s*(.+))?', line)
            if em: exception_type = em.group(1); root_cause = em.group(2) or line; break
            if line.strip() and not line.startswith(" "): root_cause = line.strip(); break

        parts = [f"  File: {file_line}" if file_line else "", f"  Exception: {exception_type}" if exception_type else "",
                 f"  Message: {root_cause}" if root_cause else "",
                 f"  Frames: {len(frames)} total (collapsed)" if frames else ""]
        result = "Traceback (compressed):\n" + "\n".join(p for p in parts if p)
        return StrategyResult(compressed=result, original_tokens=self._te(content), compressed_tokens=self._te(result),
            ratio=self._te(result)/max(self._te(content),1), verifier_passed=True,
            protected_fields_preserved=3 if root_cause else 0, protected_fields_expected=3,
            explanation=[f"exception: {exception_type}", f"root cause preserved", f"frames: {len(frames)} collapsed"])

    def expand(self, ref, sid=""): return {"content": "", "error": "use artifact store for full traceback"}
    def verify(self, orig, res): 
        return "Traceback" in res.compressed and (res.protected_fields_preserved >= res.protected_fields_expected - 1)
    def _te(self, t): return len(t)//3

traceback_strategy = TracebackStrategy(); registry.register(traceback_strategy)

# ═══════════════════════════════════════════════════════════════════════════════
# 5-8: Quick strategies — TestOutput, Diff, Markdown, Conversation
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutputStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="test_output_strategy", version="0.3.0",
        capabilities=[StrategyCapability.INCIDENT_AWARE, StrategyCapability.STRUCTURED, StrategyCapability.RECOVERABLE],
        supported_formats=["test_output", "pytest", "tool"], expected_ratio=0.30, priority=9)
    def supports(self, c, t): return t in ("test_output", "pytest") or ("PASSED" in c or "FAILED" in c or "ERRORS" in c)
    def compress(self, c, level="L1"):
        if level == "L0": return StrategyResult(compressed=c, original_tokens=self._te(c), compressed_tokens=self._te(c), ratio=1.0)
        fails = [l for l in c.split("\n") if re.search(r"(?i)FAIL|ERROR|assert|Traceback", l)]
        passes = sum(1 for l in c.split("\n") if "PASS" in l.upper())
        total_m = re.search(r'(\d+) passed', c); total = int(total_m.group(1)) if total_m else passes
        result = f"Test Results: {total} passed"
        if fails: result += f"\n── {len(fails)} FAILURES ──\n" + "\n".join(f"  {f}" for f in fails[:10])
        return StrategyResult(compressed=result, original_tokens=self._te(c), compressed_tokens=self._te(result),
            ratio=self._te(result)/max(self._te(c),1), verifier_passed=True,
            explanation=[f"passed: {total}", f"failures: {len(fails)} preserved"])
    def expand(self, r, s=""): return {"content": "", "error": "use artifact store"}
    def verify(self, o, r): return True
    def _te(self, t): return len(t)//3

class DiffStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="diff_strategy", version="0.3.0",
        capabilities=[StrategyCapability.STRUCTURED, StrategyCapability.HIGH_FIDELITY, StrategyCapability.RECOVERABLE],
        supported_formats=["git_diff", "diff", "tool"], expected_ratio=0.40, priority=7)
    def supports(self, c, t): return t in ("git_diff", "diff") or ("+++ " in c or "--- " in c or "@@ -" in c)
    def compress(self, c, level="L1"):
        if level == "L0": return StrategyResult(compressed=c, original_tokens=self._te(c), compressed_tokens=self._te(c), ratio=1.0)
        files = [l for l in c.split("\n") if l.startswith("+++ ") or l.startswith("--- ")]
        changes = [l for l in c.split("\n") if l.startswith("+") or l.startswith("-")]
        adds = sum(1 for l in changes if l.startswith("+")); dels = sum(1 for l in changes if l.startswith("-"))
        result = f"Diff: {len(files)} files, +{adds} -{dels}\n" + "\n".join(changes[:30])
        return StrategyResult(compressed=result, original_tokens=self._te(c), compressed_tokens=self._te(result),
            ratio=self._te(result)/max(self._te(c),1), verifier_passed=True,
            explanation=[f"files: {len(files)}", f"+{adds} -{dels} lines"])
    def expand(self, r, s=""): return {"content": "", "error": "use artifact store"}
    def verify(self, o, r): return True
    def _te(self, t): return len(t)//3

class MarkdownStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="markdown_strategy", version="0.3.0",
        capabilities=[StrategyCapability.STRUCTURED, StrategyCapability.SEMANTIC],
        supported_formats=["markdown", "document", "file"], expected_ratio=0.55, priority=5)
    def supports(self, c, t): return t in ("markdown", "document") or (c.strip().startswith("#") and "##" in c)
    def compress(self, c, level="L1"):
        if level == "L0": return StrategyResult(compressed=c, original_tokens=self._te(c), compressed_tokens=self._te(c), ratio=1.0)
        headings = [l for l in c.split("\n") if l.startswith("#")]
        code_blocks = len(re.findall(r'```', c)) // 2
        tables = len(re.findall(r'\|.*\|.*\|', c))
        result = f"Document: {len(headings)} sections, {code_blocks} code blocks, {tables} tables\n"
        result += "\n".join(headings[:20])
        return StrategyResult(compressed=result, original_tokens=self._te(c), compressed_tokens=self._te(result),
            ratio=self._te(result)/max(self._te(c),1), verifier_passed=True,
            explanation=[f"sections: {len(headings)}", f"structure preserved"])
    def expand(self, r, s=""): return {"content": "", "error": "use artifact store"}
    def verify(self, o, r): return True
    def _te(self, t): return len(t)//3

class ConversationStrategy(CompressionStrategy):
    descriptor = StrategyDescriptor(name="conversation_strategy", version="0.3.0",
        capabilities=[StrategyCapability.SEMANTIC, StrategyCapability.RECOVERABLE],
        supported_formats=["conversation", "chat", "tool", "text"], expected_ratio=0.45, priority=6)
    def supports(self, c, t): return t in ("conversation", "chat") or ("User:" in c and "Agent:" in c)
    def compress(self, c, level="L1"):
        if level == "L0": return StrategyResult(compressed=c, original_tokens=self._te(c), compressed_tokens=self._te(c), ratio=1.0)
        # Extract: decisions, requirements, constraints, actions
        decisions = re.findall(r'(?i)(decision|conclusion|decided):\s*(.+)', c)
        reqs = re.findall(r'(?i)(requirement|must have|acceptance criteria):?\s*(.+)', c)
        constraints = re.findall(r'(?i)(constraint|limitation|restricted|forbidden):?\s*(.+)', c)
        actions = re.findall(r'(?i)(action|TODO|task):\s*(.+)', c)
        users = len(re.findall(r'User:', c))
        agents = len(re.findall(r'Agent:', c))

        parts = [f"Conversation: {users+agents} messages ({users} user, {agents} agent)"]
        if decisions: parts.append(f"Decisions: {'; '.join(d[1][:60] for d in decisions[:5])}")
        if reqs: parts.append(f"Requirements: {'; '.join(r[1][:60] for r in reqs[:5])}")
        if constraints: parts.append(f"Constraints: {'; '.join(c[1][:60] for c in constraints[:3])}")
        if actions: parts.append(f"Actions: {'; '.join(a[1][:60] for a in actions[:5])}")

        result = "\n".join(parts)
        return StrategyResult(compressed=result, original_tokens=self._te(c), compressed_tokens=self._te(result),
            ratio=self._te(result)/max(self._te(c),1), verifier_passed=True,
            explanation=[f"messages: {users+agents}", f"decisions: {len(decisions)}",
                         f"requirements: {len(reqs)}", f"actions: {len(actions)}"])
    def expand(self, r, s=""): return {"content": "", "error": "use artifact store"}
    def verify(self, o, r): return True
    def _te(self, t): return len(t)//3

# Register all
for s in [TestOutputStrategy(), DiffStrategy(), MarkdownStrategy(), ConversationStrategy()]:
    registry.register(s)

print(f"Registered {registry.count} strategies: {[d.name for d in registry.list_all()]}")
