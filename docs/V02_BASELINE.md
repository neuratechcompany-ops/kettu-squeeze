# v0.1 Baseline — Kettu Squeeze

**Date:** 2026-07-12 | **Commit:** 1a662ce | **Tests:** 92 PASS, 1 SKIP

## Current Policies (static, format-based)

| Source Type | Mode | Lossless |
|-------------|------|----------|
| source_code | strict_raw | ✅ |
| config | strict_raw | ✅ |
| sql | strict_raw | ✅ |
| markdown | strict_raw | ✅ |
| log | lossless | ✅ |
| json | lossless | ✅ |
| test_output | lossless | ✅ |
| git_diff | lossless | ✅ |
| default | lossless | ✅ |

## Decision Model

- **STATIC**: policy lookup by `source_type` — no budget awareness
- **RULE-BASED**: compressor selection by `policy.mode`
- **FORMAT-BASED**: compressor dispatch by input format
- **BUDGET-UNAWARE**: no context window consideration
- **TASK-UNAWARE**: no task metadata
- **COST-UNAWARE**: no expand cost estimation

## Compressors

- Log compressor: RLE-based, preserves first/last, error counts
- JSON compressor: null-stripping (opt-in), compact encoding
- Test output: aggregates passes, preserves failures with tracebacks
- Git diff: structural summarization, line preservation
- Source code: strict_raw (untouched)

## Known Limitations

1. All decisions are static — same input always gets same treatment
2. No budget awareness — compresses even when context window is mostly empty
3. No KEEP_RAW decision — every input goes through compressor
4. No multi-level compression — binary choice: RAW or COMPRESSED
5. No semantic importance scoring
6. No cost model for expand operations
7. No protected field mechanism beyond lossless mode
8. No dry-run or shadow mode

## Metrics (from benchmark)

- COS: 96.1 EXCELLENT
- DeepSeek v4 Pro A/B: ΔQ 0%, NAB +0.011
- GPT-OSS 120B: ΔQ 0%, NAB +0.012
- Typical savings: Docker logs 25.3%, JSON 26.5%
- Edge cases: K8s logs −11.1% (short structured text)
- Broken refs: 0
- Cross-session leaks: 0
- Unicode crashes: 0

## Artifact Store

- Content-addressed (SHA-256)
- Immutable blobs
- Session-aware references
- Persistent but not context-visible by default
