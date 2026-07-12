#!/usr/bin/env python
"""Kettu Eval v0.2 Shadow Comparison Runner.

Compares Legacy v0.1 vs Adaptive v0.2 on context-core scenarios.
Requires: kettu-eval package installed.

Usage:
    python scripts/eval_v02_shadow.py [--limit N]
"""

import sys
import json
import time
from pathlib import Path

try:
    from kettu_eval.runners.context_runner import ContextRunner
    from kettu_eval.adapters.null_adapter import NullContextAdapter
except ImportError:
    print("kettu-eval not installed. Run: pip install -e /path/to/kettu-eval")
    sys.exit(1)

from kettu_squeeze.policy.engine import AdaptivePolicyEngine
from kettu_squeeze.policy.bridge import EngineBridge
from kettu_squeeze.policy.execution import ExecutionMode
from kettu_squeeze.policy.models import ContextBudget
from kettu_squeeze.shadow.models import ShadowComparator, ShadowStorage


def main(limit: int = None):
    bridge = EngineBridge()
    comparator = ShadowComparator()
    storage = ShadowStorage(".kettu-squeeze/shadow")

    # Load scenarios from Kettu Eval
    runner = ContextRunner()
    scenarios = runner.load_scenarios()
    if limit:
        scenarios = scenarios[:limit]

    results = []
    wins = {"adaptive_win": 0, "legacy_win": 0, "tie": 0, "invalid_comparison": 0,
            "adaptive_failed": 0, "legacy_failed": 0}

    for i, sc in enumerate(scenarios):
        content = sc.get("input_content", "")
        if not content and "input_fixture" in sc:
            fp = runner.dataset_path / sc["input_fixture"]
            content = fp.read_text() if fp.exists() else ""

        if not content:
            continue

        source_type = sc.get("source_type", "unknown")
        budget = ContextBudget(current_tokens=len(content)//3 + 10000,
                               model_context_limit=131072)

        # Run shadow comparison
        _, _, shadow = bridge.compress(
            content, session_id=f"eval-{i}", source_type=source_type,
            source_path=sc.get("source_path", ""), mode=ExecutionMode.SHADOW,
            context_budget=budget,
        )

        if shadow:
            results.append(shadow)
            wins[shadow.verdict] = wins.get(shadow.verdict, 0) + 1
            storage.persist(shadow)

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(scenarios)}] {wins}")

    print(f"\n═══ Shadow Comparison Results ═══")
    total = len(results)
    for verdict, count in sorted(wins.items(), key=lambda x: -x[1]):
        pct = count / max(total, 1) * 100
        print(f"  {verdict:25s}: {count:3d} ({pct:.0f}%)")

    print(f"\n  Total scenarios: {total}")
    print(f"  Results saved: .kettu-squeeze/shadow/")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].startswith("--limit=") else None
    if limit is None and len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass
    main(limit)
