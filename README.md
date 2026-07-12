# Kettu Squeeze

**Recoverable Context Optimization for AI Agents.**

Not a compressor. An optimization engine that answers "what can be safely reduced?" — not "how much can we remove?"

**v0.1.0 — RELEASE WITH LIMITATIONS** · commit `0a717ef` · [Full Audit](docs/AUDIT_REPORT.md)

## Release Status

| Gate | Result |
|------|--------|
| Tests | 92/92 PASS |
| Soak (10K events) | 0 errors, 0 broken refs |
| COS | 96.1 EXCELLENT |
| DeepSeek v4 Pro A/B | ΔQuality 0%, NAB +0.011 |
| GPT-OSS 120B | ΔQuality 0%, NAB +0.012 (10/11 scenarios) |
| CRITICAL/HIGH findings | 0 open |
| Hard gates | all clean |

## Limitations (read before using)

1. **No concurrent write safety testing.** SQLite WAL mode but not stress-tested under high-concurrency writes. Safe for single-agent MCP usage.
2. **`squeeze_run_and_compress` uses `shell=True`.** No command allowlist. Acceptable for agent-controlled commands, not for untrusted input.
3. **API endpoints unauthenticated.** FastAPI server is localhost-only by design. Do not expose to networks without adding auth.

Full list: [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md)

## Principles

- **Raw is authoritative.** Compression is a view, never the source of truth.
- **Lossless by default.** Lossy requires explicit policy and recoverable refs.
- **Session-aware.** Storage cache ≠ model visibility.
- **Verify everything.** Every compressed output passes through a verifier.
- **Recoverable only.** Every omission has a resolvable reference.

## What Kettu Squeeze does NOT do

- No entropy truncation of source code
- No irreversible content deletion
- No cross-session reference leaks
- No delta without visible base
- No byte-index slicing without UTF-8 boundary checks
- No benchmark claims without agent quality measurement

## Benchmark

```
11 scenarios, 220 actions
3.6% avg token savings

Source code:   0.0%  (STRICT_RAW)
Docker logs:  25.3%  (RLE)
JSON:          1.9×  (compact encoding)
Long session: -1.6%  (neutral)
```

| Model | Recall | ΔQuality | NAB |
|-------|--------|----------|-----|
| DeepSeek v4 Pro | 100% | 0.0% | +0.011 |
| GPT-OSS 120B | 100% | 0.0% | +0.012 |

## Install

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
kettu-squeeze compress server.log
kettu-squeeze expand "artifact:<id>:L10-L50"
kettu-squeeze doctor
kettu-squeeze-mcp  # MCP server
```

## Hermes Integration

```json
// ~/.hermes/mcp.json
{"mcpServers": {"kettu-squeeze": {"command": "kettu-squeeze-mcp"}}}
```

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Invariants](docs/INVARIANTS.md) · [Security](docs/SECURITY.md) · [Audit](docs/AUDIT_REPORT.md) · [Limitations](docs/KNOWN_LIMITATIONS.md) · [Threat Model](docs/THREAT_MODEL.md)

## License

MIT
