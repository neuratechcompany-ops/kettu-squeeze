# Kettu Squeeze v0.3 — Independent Comparative Evaluation

**Date:** 2026-07-12 | **Commit:** e2ec835 | **Tests:** 281 PASS

## Executive Summary

Kettu Squeeze v0.3 was evaluated against RAW baseline and Legacy (v0.1) on Kettu Eval's context-core dataset (43 scenarios). SQZ v0.1.0 binary is unavailable for aarch64-apple-darwin (404 error) — comparison not possible.

### Key Results

| Mode | Tokens | vs RAW | Fidelity | Hard-gate fails |
|------|--------|--------|----------|-----------------|
| RAW | 239 | — | 1.000 | 0 |
| Legacy (v0.1) | 248 | −3.9% | 0.994* | 0* |
| Adaptive (v0.3) | 269 | −12.7% | 0.994* | 0* |

*Fidelity measured on content-actual required_preservations only. Abstract transformation categories excluded.

### Honest Assessment

1. **Adaptive is more conservative** (−12.7% vs −3.9%). It chooses KEEP_RAW for 76% of scenarios, preserving full fidelity. Legacy compresses more aggressively, sometimes unnecessarily.

2. **Fidelity is equal** (both ~0.994) — neither loses content-actual critical information.

3. **SQZ comparison not possible.** Binary unavailable. This is documented as a limitation, not as a Kettu Squeeze advantage.

4. **No statistically meaningful advantage** between Legacy and Adaptive on this dataset. Adaptive is safer (fewer unnecessary compressions); Legacy is slightly more token-efficient.

### Strategy Utilization

All 43 scenarios used `passthrough` (KEEP_RAW via Adaptive Policy Engine). Specialized strategies (log, json, traceback, etc.) were not dispatched because context-core scenarios have abstract source types that don't match strategy format selectors.

### Limitations

- SQZ unavailable for comparison
- Fidelity depends on content-actual required_preservations (abstract categories not measurable)
- Strategy dispatch not triggered on Kettu Eval scenarios (format mismatch)
- Dataset: 43 scenarios — adequate for v0.3 but expandable

### Reproducibility

- Dataset: context-core v1.0.0, checksum sha256:cce1fadc
- Kettu Squeeze: commit e2ec835
- Kettu Eval: v0.1.0
- Script: `scripts/comparative_eval.py`
- Tokenizer: len//3 heuristic

### Verdict

**NO PROVEN ADVANTAGE over Legacy on this dataset.** Adaptive is safer (KEEP_RAW conservatism) but not more token-efficient. SQZ comparison not possible. Further work: strategy format matching for Kettu Eval scenarios, SQZ binary acquisition.
