#!/usr/bin/env python
"""Kettu Squeeze v0.3 — Independent Comparative Evaluation.

Compares: RAW | Legacy Kettu | Adaptive Kettu | SQZ (if available)
Uses Kettu Eval context-core dataset as ground truth.
All results reproducible. No policy tuning after dataset freeze.
"""
import json, time, statistics, sys, os
from pathlib import Path
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════════
print("═══ Kettu Squeeze v0.3 — Comparative Evaluation ═══\n")

# Kettu Eval — must run from its directory for dataset discovery
KE_DIR = Path(os.environ.get("KETTU_EVAL_DIR", str(Path.home() / "kettu-eval")))
sys.path.insert(0, str(KE_DIR))

try:
    from kettu_eval.runners.context_runner import ContextRunner
except ImportError:
    print(f"ERROR: kettu-eval not found at {KE_DIR}")
    sys.exit(1)

# Kettu Squeeze
from kettu_squeeze.policy.bridge import EngineBridge
from kettu_squeeze.policy.execution import ExecutionMode

# SQZ
SQZ_AVAILABLE = False
SQZ_REASON = "Binary download failed (404). SQZ v0.1.0 binary not available for aarch64-apple-darwin."
try:
    from sqz import compress as sqz_compress
    SQZ_AVAILABLE = True
except ImportError:
    pass

print(f"SQZ: {'AVAILABLE' if SQZ_AVAILABLE else 'UNAVAILABLE — ' + SQZ_REASON}")

# ═══════════════════════════════════════════════════════════════════════════════
# Load scenarios from Kettu Eval dataset
# ═══════════════════════════════════════════════════════════════════════════════
os.chdir(str(KE_DIR))  # ContextRunner uses relative paths
runner = ContextRunner()
scenarios = runner.load_scenarios()
os.chdir(str(Path.home() / "kettu-squeeze"))  # Back to squeeze dir
print(f"Dataset: context-core, {len(scenarios)} scenarios")

# ═══════════════════════════════════════════════════════════════════════════════
# Run all modes
# ═══════════════════════════════════════════════════════════════════════════════
bridge = EngineBridge()
results = {"raw": [], "legacy": [], "adaptive": [], "sqz": []}
fidelity = {"raw": [], "legacy": [], "adaptive": [], "sqz": []}
latency = {"raw": [], "legacy": [], "adaptive": [], "sqz": []}
hard_gate_fails = {"raw": 0, "legacy": 0, "adaptive": 0, "sqz": 0}
protected_lost = {"raw": 0, "legacy": 0, "adaptive": 0, "sqz": 0}
strategy_hits = defaultdict(int)

for i, sc in enumerate(scenarios):
    content = sc.get("input_content", "")
    if not content and "input_fixture" in sc:
        os.chdir(str(KE_DIR))
        fp = runner.dataset_path / sc["input_fixture"]
        content = fp.read_text() if fp.exists() else ""
        os.chdir(str(Path.home() / "kettu-squeeze"))
    if not content:
        continue

    st = sc.get("source_type", "tool")
    sp = sc.get("source_path", "")
    required = sc.get("required_preservations", [])
    in_tok = len(content) // 3

    # ── RAW ──
    results["raw"].append(in_tok)
    fidelity["raw"].append(1.0)

    # ── LEGACY ──
    t0 = time.perf_counter()
    resp, _, _ = bridge.compress(content, f"s{i}", source_type=st, source_path=sp, mode=ExecutionMode.LEGACY)
    ms = (time.perf_counter() - t0) * 1000
    results["legacy"].append(resp.compressed_tokens)
    latency["legacy"].append(ms)
    # Fidelity: check required_preservations
    found = sum(1 for r in required if r.lower() in resp.content.lower())
    fid = found / max(len(required), 1) if required else 1.0
    fidelity["legacy"].append(fid)
    if fid < 0.99:
        hard_gate_fails["legacy"] += 1

    # ── ADAPTIVE ──
    t0 = time.perf_counter()
    resp, report, _ = bridge.compress(content, f"s{i}", source_type=st, source_path=sp,
                                        mode=ExecutionMode.ADAPTIVE)
    ms = (time.perf_counter() - t0) * 1000
    results["adaptive"].append(resp.compressed_tokens)
    latency["adaptive"].append(ms)
    if report:
        strategy_hits[report.strategy_used] += 1
    found = sum(1 for r in required if r.lower() in resp.content.lower())
    fid = found / max(len(required), 1) if required else 1.0
    fidelity["adaptive"].append(fid)
    if fid < 0.99:
        hard_gate_fails["adaptive"] += 1

    # ── SQZ ──
    if SQZ_AVAILABLE:
        t0 = time.perf_counter()
        try:
            sqz_result = sqz_compress(content)
            sqz_tok = len(sqz_result) // 3
            results["sqz"].append(sqz_tok)
            fidelity["sqz"].append(1.0)  # SQZ doesn't expose fidelity
        except Exception:
            results["sqz"].append(in_tok)
            fidelity["sqz"].append(1.0)
        ms = (time.perf_counter() - t0) * 1000
        latency["sqz"].append(ms)

    if (i + 1) % 10 == 0:
        r = statistics.mean(results["raw"]); l = statistics.mean(results["legacy"])
        a = statistics.mean(results["adaptive"])
        s = statistics.mean(results["sqz"]) if results["sqz"] else 0
        print(f"[{i+1}/{len(scenarios)}] R={r:.0f} L={l:.0f} A={a:.0f} S={s:.0f}")

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
r_mean = statistics.mean(results["raw"]) if results["raw"] else 0
l_mean = statistics.mean(results["legacy"]) if results["legacy"] else 0
a_mean = statistics.mean(results["adaptive"]) if results["adaptive"] else 0
s_mean = statistics.mean(results["sqz"]) if results["sqz"] else 0

print(f"\n═══ Results ═══")
print(f"{'Mode':12s} {'Tokens':>8s} {'vs RAW':>8s} {'Fidelity':>9s} {'HGFails':>8s} {'p50ms':>7s}")
for mode, label in [("raw", "RAW"), ("legacy", "Legacy"), ("adaptive", "Adaptive"), ("sqz", "SQZ")]:
    if not results[mode]:
        continue
    tok = statistics.mean(results[mode])
    red = (r_mean - tok) / max(r_mean, 1) * 100
    fid = statistics.median(fidelity[mode]) if fidelity[mode] else 1.0
    hg = hard_gate_fails[mode]
    lt = statistics.median(latency[mode]) if latency[mode] else 0
    print(f"{label:12s} {tok:>8.0f} {red:>+7.1f}% {fid:>8.3f} {hg:>8d} {lt:>6.1f}")

if SQZ_AVAILABLE:
    sqz_vs_legacy = (l_mean - s_mean) / max(l_mean, 1) * 100
    sqz_vs_adaptive = (a_mean - s_mean) / max(a_mean, 1) * 100
    print(f"\nSQZ vs Legacy:   {sqz_vs_legacy:+.1f}%")
    print(f"SQZ vs Adaptive: {sqz_vs_adaptive:+.1f}%")

# Strategy utilization
if strategy_hits:
    print(f"\n═══ Strategy Utilization ═══")
    for name, count in sorted(strategy_hits.items(), key=lambda x: -x[1]):
        print(f"  {name:30s} {count:3d}")

# Save
report = {
    "dataset": "context-core", "scenarios": len(results["raw"]),
    "raw_mean_tokens": r_mean,
    "legacy": {"mean_tokens": l_mean, "reduction_pct": (r_mean-l_mean)/max(r_mean,1)*100,
               "median_fidelity": statistics.median(fidelity["legacy"]) if fidelity["legacy"] else 1.0,
               "hard_gate_fails": hard_gate_fails["legacy"],
               "p50_ms": statistics.median(latency["legacy"]) if latency["legacy"] else 0},
    "adaptive": {"mean_tokens": a_mean, "reduction_pct": (r_mean-a_mean)/max(r_mean,1)*100,
                 "median_fidelity": statistics.median(fidelity["adaptive"]) if fidelity["adaptive"] else 1.0,
                 "hard_gate_fails": hard_gate_fails["adaptive"],
                 "p50_ms": statistics.median(latency["adaptive"]) if latency["adaptive"] else 0,
                 "strategies": dict(strategy_hits)},
}
if SQZ_AVAILABLE:
    report["sqz"] = {"mean_tokens": s_mean, "reduction_pct": (r_mean-s_mean)/max(r_mean,1)*100,
                     "median_fidelity": 1.0, "hard_gate_fails": 0,
                     "p50_ms": statistics.median(latency["sqz"]) if latency["sqz"] else 0}

Path("reports/comparative_eval.json").parent.mkdir(parents=True, exist_ok=True)
Path("reports/comparative_eval.json").write_text(json.dumps(report, indent=2))
print(f"\nReport: reports/comparative_eval.json")
