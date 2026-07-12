# Kettu Squeeze — Whitepaper v0.3

## Abstract

Kettu Squeeze is a recoverable context optimization engine for AI agents. Unlike traditional compressors that maximize token reduction at any cost, Kettu Squeeze optimizes for **safe, recoverable context reduction** — preserving critical information while minimizing context window pressure. v0.3 introduces an Adaptive Policy Engine and specialized Compression Strategy Framework.

## Architecture

### Three-Layer Design

1. **Adaptive Policy Engine** — decides when and how to compress based on context budget, content importance, and risk assessment
2. **Compression Strategy Framework** — 8 specialized strategies (log, json, python, traceback, conversation, markdown, diff, test_output) with capability-based dispatch
3. **Execution Layer** — Artifact Store for content-addressed storage, Context Ledger for session-aware references, Verifier for integrity

### Key Invariants

- Raw artifacts immutable
- References recoverable
- Verification mandatory — failure returns raw
- Source code always strict_raw
- Protected fields never lost
- Hard gates override numeric scores

## Evaluation

See [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md) for full comparative results.

## Status

v0.3 — Experimental. 281 tests. 8 strategies. 320-scenario benchmark.
