# Kettu Squeeze v0.3 — Corrected Comparative Evaluation

**Date:** 2026-07-12 | **Commit:** 62dec32 | **Tests:** 281 PASS

## Honest Results (43 scenarios, context-core dataset)

| Mode | Output tokens | Δ vs RAW | Δ % | Fidelity |
|------|---------------|----------|-----|----------|
| RAW | 239 | — | — | 1.000 |
| Kettu Legacy (v0.1) | 248 | +9 | **+3.9%** | 1.000 |
| Kettu Adaptive (v0.3) | 269 | +30 | **+12.7%** | 1.000 |
| **SQZ v1.3.0** | **166** | **−73** | **−30.5%** | 0.979 |

**Positive Δ% = growth (bad). Negative Δ% = reduction (good).**

## Key Findings

1. **SQZ compresses better.** −30.5% vs +3.9%/+12.7%. On this dataset of small inputs (mean 239 tokens), SQZ reduces context size while Kettu Squeeze increases it due to engine metadata overhead.

2. **Kettu Squeeze fidelity is higher.** 1.000 vs 0.979. Kettu Squeeze preserves all content-actual required strings; SQZ loses 2.1% of them.

3. **Kettu Adaptive is worse than Legacy.** +12.7% vs +3.9%. Adaptive's KEEP_RAW conservatism adds overhead without compression benefit on small inputs.

4. **SQZ wins on token reduction.** Kettu Squeeze wins on fidelity. Trade-off.

## Why Kettu Squeeze Underperforms

- **Small inputs (mean 239 tokens):** Engine adds artifact registration, ledger entries, verification metadata — overhead dominates savings.
- **KEEP_RAW policy (76% of scenarios):** Adaptive skips compression on most scenarios, adding passthrough overhead.
- **Context-core dataset designed for Kettu Squeeze v0.1:** Many scenarios are adversarial/small — not representative of real agent workloads.

## SQZ Details

- Version: v1.3.0 (latest release, June 2026)
- Binary: aarch64-apple-darwin, 14MB
- Binary available from GitHub Releases
- Python wrapper (v0.1.0) is outdated — uses v1.3.0 binary directly

## Per-Scenario Data

See `reports/per_scenario.csv` and `reports/comparative_eval_v2.json`.

## Limitations

- Dataset: 43 small scenarios — not representative of production agent workloads
- Fidelity measured on content-actual strings only — abstract transformation categories excluded
- SQZ run via CLI pipe — no Python API available
- Kettu Squeeze overhead is structural (metadata, verification) — benefits appear on larger inputs

## Verdict

**SQZ v1.3.0 is better than Kettu Squeeze v0.3 on this dataset for token reduction.** Kettu Squeeze has higher fidelity. The comparison is unfair to Kettu Squeeze on small inputs (engine overhead dominates). A fairer comparison would use larger production-representative scenarios (1000+ tokens).

**No statistically meaningful advantage for Kettu Squeeze on this dataset.**
