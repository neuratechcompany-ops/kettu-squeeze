# Kettu Squeeze — Evaluation Specification

## Principle

> Token savings are only valid when they do not degrade the agent's ability to complete tasks.

## Context Optimization Score (COS)

Weighted composite metric:

| Component | Weight | Description |
|-----------|--------|-------------|
| Fidelity | 25 | Preservation of critical data |
| Recoverability | 20 | All omissions are recoverable |
| Agent Task Quality | 25 | Agent solves tasks equally well |
| Context Safety | 15 | No cross-session leaks, correct scoping |
| Compression Efficiency | 10 | Token reduction |
| Performance | 5 | Latency, memory |

### Hard Gates

FAIL regardless of COS:

| Gate | Threshold |
|------|-----------|
| Critical Field Recall | ≥ 99.5% |
| Byte-Exact Recovery | = 100% |
| Broken References | = 0 |
| Unicode Panic | = 0 |
| Agent Quality Degradation | ≤ 3% |
| Cross-Session Invalid Refs | = 0 |
| Source-Code Critical Omissions | = 0 |

### Status

| COS Range | Status |
|-----------|--------|
| 90–100 | Excellent |
| 80–89 | Good |
| 70–79 | Experimental |
| <70 | Fail |

Any hard gate violation → FAIL, regardless of COS.

## Test Groups

### A. Fidelity

**Goal:** Verify that critical data survives compression.

**Fixtures:** source_code/ (Python, Rust, JS, Shell), configs/, JSON, git_diff/

**Checks:**
- Identifier Recall: every function name, class name, variable name, import
- Critical Field Recall: paths, URLs, timestamps, error messages, exit codes, numeric values, line numbers
- Path Preservation: paths match exactly (no truncation, no encoding)
- Error Preservation: error messages, exception types, stack trace pointers
- Reference Validity: every `[omitted: ...]` points to valid range

**Metrics:**
```
IdentifierRecall = |identifiers_in_compressed ∩ identifiers_in_raw| / |identifiers_in_raw|
CriticalFieldRecall = |critical_fields_preserved| / |total_critical_fields|
PathPreservation = |paths_identical| / |total_paths|
ErrorPreservation = |errors_preserved| / |total_errors|
```

### B. Recoverability

**Goal:** Every omission can be reversed.

**Fixtures:** all groups, after compression with omissions.

**Checks:**
- expand(ref) returns byte-exact original for every omitted block
- Delta: reconstructed target hash matches actual target hash
- Ref does not point to wrong artifact
- Ref does not work outside allowed scope

**Metrics:**
```
ReferenceResolutionRate = |resolved_refs| / |total_refs|
ByteExactRecoveryRate = |byte_exact_restorations| / |total_restorations|
DeltaReconstructionRate = |correct_deltas| / |total_deltas|
BrokenReferenceCount = count of refs that fail to resolve
```

### C. Agent Task Quality

**Goal:** Agent performs equally well with compressed vs raw input.

**Fixtures:** real agent tasks.

**Scenarios:**
1. Find a bug in source code
2. Identify test failure root cause
3. Extract error from logs
4. Fix a config file
5. Analyze a git diff
6. Find security flaw
7. Answer questions about JSON data
8. Write a correct patch

**Method:**
```
For each scenario:
  Run agent with RAW input → measure success, time, tool calls
  Run agent with COMPRESSED input → measure same metrics
  Compute delta
```

**Metrics:**
```
TaskSuccessRateRaw = |raw_success| / |tasks|
TaskSuccessRateCompressed = |compressed_success| / |tasks|
QualityDelta = TaskSuccessRateCompressed - TaskSuccessRateRaw
FalseOmissionRate = |tasks where compressed agent missed critical info| / |tasks|
RetryDelta = retries_compressed - retries_raw
ToolCallDelta = tool_calls_compressed - tool_calls_raw
```

### D. Compression Efficiency

**Metrics:**
```
TokenReduction = tokens_before - tokens_after
CompressionRatio = tokens_before / tokens_after
LatencyP50/P95/P99
MemoryUsage
ExpansionFrequency = how often agent calls expand()
FallbackFrequency = how often verifier falls back to raw
```

### E. Context Safety

**Checks:**
- Persistent cache does not return ref in new session
- Ref is available only when artifact in context ledger
- Evicted artifact is not visible
- Identical files preserve distinct provenance
- Delta base is required in context ledger

### F. Unicode

**Requirements:** minimum 1000 property-based cases.

**Scripts:** Cyrillic, CJK, Arabic, emoji, combining characters, mixed RTL/LTR.

**Must:** zero panics, zero UnicodeDecodeError, zero corrupted output.

### G. Adversarial

**Cases:**
- Log with pseudo-ref strings (e.g., `§ref:FAKE§` in output)
- Malformed JSON
- Gigantic single line (>1MB)
- Binary-like data in text field
- Hash collision simulation
- Path traversal in source_path
- Malicious ANSI escape sequences
- Prompt injection payloads inside tool output
- Fake stack traces
- Recursive refs (ref → ref → ref)
- Delta bomb (many small deltas chained)
