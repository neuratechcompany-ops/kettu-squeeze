# Kettu Squeeze v0.5 — Scientific Validation Report

**Date:** 2026-07-12 | **Commit:** 8c9fbef | **Workflows:** 1000 | **Holdout:** 147

## Executive Summary

Task-aware compression preserves 100% of critical facts but does not compress — output is 25% larger than input due to collapse markers and metadata. SQZ compresses 35% but loses critical facts in 42% of cases. Task detection does not measurably help — planner rules are generic.

## Results (Holdout, 147 workflows)

| Mode | Crit Survival | 95% CI | Reduction | Unsafe |
|------|---------------|--------|-----------|--------|
| RAW | **1.000** | [1.000, 1.000] | 0.0% | 0 |
| P1 | **1.000** | [1.000, 1.000] | +3.1% | 0 |
| v0.5 | **1.000** | [1.000, 1.000] | −25.2% | 0 |
| SQZ | 0.578 | [0.498, 0.658] | **+35.0%** | **62** |

**Positive reduction = compression. Negative = expansion.**

## Pareto Frontier

```
Crit Survival ↑
1.000 ───●RAW ●P1 ●v05
0.578 ───────────────────────●SQZ
       0%              35%    Token Reduction →
```

**No single point dominates.** RAW/P1/v05: perfect safety, no compression. SQZ: real compression, 42% unsafe.

## Category Analysis

| Category | RAW | SQZ | P1 | v05 | SQZ Unsafe |
|----------|-----|-----|-----|-----|------------|
| docker | 1.0 | 0.18 | 1.0 | 1.0 | 82% |
| kubernetes | 1.0 | 0.05 | 1.0 | 1.0 | 95% |
| git | 1.0 | 0.25 | 1.0 | 1.0 | 75% |
| logs | 1.0 | 1.0 | 1.0 | 1.0 | 0% |
| debugging | 1.0 | 1.0 | 1.0 | 1.0 | 0% |
| test_fixing | 1.0 | 1.0 | 1.0 | 1.0 | 0% |

SQZ is unsafe on structured outputs (docker, k8s, git) but safe on text (logs, debugging).

## Ablation Study

| Component | Crit Survival | Output Tokens |
|-----------|---------------|---------------|
| v05_full | 1.000 | 39 |
| v05_no_detect | 1.000 | 39 |
| v05_no_plan | 1.000 | 32 |

**Task detection has zero impact** — planner produces identical output without it. v05_no_plan (passthrough) produces smaller output (32 vs 39) — task planning adds 7 tokens of collapse markers.

## Significance

v05 vs SQZ paired comparison: 62 better, 85 equal, 0 worse. Mean diff: +0.422.

v05 is SAFER than SQZ in 62/147 cases (42%). But v05 is identical to P1 and RAW — it adds no compression benefit.

## Honest Conclusions

1. **Task-aware compression does not compress.** Output grows 25% due to metadata/collapse markers.
2. **Task detection has no measurable impact.** Planner rules are generic and identical with/without detection.
3. **SQZ is the only real compressor** (35% reduction) but unsafe on structured outputs (docker 82%, k8s 95%, git 75%).
4. **P1 = RAW in safety** — formatters passthrough unchanged content.

## Verdict

**TASK-AWARE COMPRESSION: NO PROVEN ADVANTAGE.**

v0.5 preserves 100% of critical facts (good) but expands output by 25% (bad). It is a safe-mode compressor but not a compression optimizer. The core challenge remains: how to compress structured data without losing critical facts — the SQZ trade-off (more compression = more data loss) is real and unsolved.
