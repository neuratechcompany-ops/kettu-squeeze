# Kettu Squeeze v0.4 — Final Comparative Report

**Commit:** 6cbd44b | **Tests:** 325 PASS | **Tokenizer:** tiktoken cl100k_base

## Two Datasets, Two Different Stories

### Dataset A: Generic Context (context-core, 43 scenarios)

Logs, JSON, source code, markdown, adversarial. No command structure.

| Mode | Reduction | Fidelity |
|------|-----------|----------|
| RAW | baseline | 1.000 |
| Kettu Legacy | −5.3% | 1.000 |
| Kettu Adaptive | −5.3% | 1.000 |
| **SQZ v1.3.0** | **−30.5%** | 0.979 |

**Winner: SQZ.** On generic text, SQZ's universal compression is more effective.

### Dataset B: Command-Aware Tool Outputs (500 scenarios)

Docker, kubectl, pytest, git, JSON tool outputs, system CLI. Structured command output.

| Mode | Reduction | Notes |
|------|-----------|-------|
| RAW | baseline | — |
| **Kettu P1** | **30%** | 20 formatters, structural knowledge |
| SQZ | 0% | Passes through — no command-aware formatters |

**Winner: Kettu P1.** Formatter-based compression exploits command structure.

### Session-Level (100 pairs)

Repeated tool outputs, test-fix-test cycles, growing logs, JSON updates.

| Mode | Reduction |
|------|-----------|
| Kettu P0 (dedup) | 46% |
| **Kettu P1 (dedup+delta)** | **82%** |
| SQZ | 20% |

**Winner: Kettu P1.** Session dedup + delta compression dominates.

## Category Breakdown

| Category | Kettu P1 | SQZ | Winner |
|----------|----------|-----|--------|
| Docker | 87% | 0% | Kettu |
| Kubernetes | 91% | 0% | Kettu |
| Test outputs | 64% | 0% | Kettu |
| System CLI | 29% | 0% | Kettu |
| JSON | 18% | 0% | Kettu |
| Git | 7% | 0% | Kettu |
| Logs | 0% | 0% | TIE |
| Mixed | −14% | 0% | SQZ |

## Honest Verdict

| Dataset | Winner | Why |
|---------|--------|-----|
| Generic text/logs | **SQZ** | Universal compression, entropy-based |
| Command outputs | **Kettu** | Command-aware formatters, structural |
| Agent sessions | **Kettu** | Dedup + delta, repeated tool outputs |
| Docker/K8s | **Kettu** | Specialized container formatters |

**SQZ is better at generic text compression. Kettu is better at agent-native tool output compression.** They are diverging into different product categories: universal context compressor vs agent-native context compressor.

## Next: Agent Workflow Benchmark

The real question is not "who compresses better" but "which compressor enables an agent to solve more tasks under a fixed context budget." Proposed next step: measure task completion rate with Kettu vs SQZ on real agent workflows.
