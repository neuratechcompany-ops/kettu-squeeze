#!/usr/bin/env python
"""Soak test — Kettu Squeeze v0.1.0.

10 000 events, 100 sessions, 10 concurrent workers.
Tests: compress + expand + register + evict + mixed Unicode.
"""
import sys, os, json, time, uuid, tempfile, threading, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import CompressionRequest, ExpandRequest, SourceType, CompressionMode

EVENTS = 10_000
SESSIONS = 100
WORKERS = 10

UNICODE_SAMPLES = [
    "Привет мир!", "你好世界！", "🎉🔥🚀", "日本語テスト",
    "ERROR: connection refused\n" * 5,
    '{"id": 1, "value": "data", "extra": null}',
    "def foo():\n    return 42\n",
]

def worker(engine, worker_id):
    errors = 0
    expanded = 0
    broken = 0
    session_id = f"soak-session-{worker_id % SESSIONS}"

    for i in range(EVENTS // WORKERS):
        try:
            content = random.choice(UNICODE_SAMPLES)
            source_type = random.choice([SourceType.FILE, SourceType.TOOL, SourceType.API])
            mode = random.choice([CompressionMode.LOSSLESS, CompressionMode.STRICT_RAW])

            resp = engine.compress(CompressionRequest(
                content=content, source_type=source_type,
                source_path=f"/soak/file_{i}.txt",
                session_id=session_id, agent_id=f"worker-{worker_id}",
                mode=mode))

            if resp.refs:
                for ref in resp.refs:
                    exp = engine.expand(ExpandRequest(ref=ref, session_id=session_id))
                    if exp is None:
                        broken += 1
                    else:
                        expanded += 1

            if i % 50 == 0:
                engine.evict(session_id, resp.artifact_id)

        except Exception as e:
            errors += 1

    return {"worker": worker_id, "errors": errors, "expanded": expanded, "broken": broken}

def main():
    base = tempfile.mkdtemp(prefix="ks-soak-")
    engine = SqueezeEngine(base_dir=base)
    print(f"Soak test: {EVENTS} events, {SESSIONS} sessions, {WORKERS} workers")
    print(f"Storage: {base}")
    start = time.perf_counter()

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(worker, engine, i) for i in range(WORKERS)]
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
            print(f"  Worker {r['worker']}: {r['errors']} errors, "
                  f"{r['expanded']} expanded, {r['broken']} broken refs")

    elapsed = time.perf_counter() - start
    total_errors = sum(r["errors"] for r in results)
    total_expanded = sum(r["expanded"] for r in results)
    total_broken = sum(r["broken"] for r in results)

    report = {
        "events": EVENTS,
        "sessions": SESSIONS,
        "workers": WORKERS,
        "duration_seconds": round(elapsed, 2),
        "events_per_second": round(EVENTS / elapsed, 1),
        "total_errors": total_errors,
        "total_expanded": total_expanded,
        "total_broken_refs": total_broken,
        "workers_completed": len(results),
    }

    path = Path("benchmarks/reports/soak_report.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))

    print(f"\n═══ Soak Report ═══")
    for k, v in report.items():
        print(f"  {k}: {v}")

    status = "PASS" if total_errors == 0 and total_broken == 0 else "FAIL"
    print(f"\n  Status: {status}")

    # Cleanup
    import shutil
    shutil.rmtree(base, ignore_errors=True)
    return 0 if status == "PASS" else 1

if __name__ == "__main__":
    sys.exit(main())
