# Known Limitations — Kettu Squeeze v0.1.0

## Compression

- **JSON null-stripping:** opt-in only (off by default). Enabled via `strip_nulls=True` marks the mode as semantically lossy — keys with null values are removed, changing `{"field": null}` to `{}`.
- **K8s/short structured output:** log compressor may increase token count (-11.1% observed) on compact table-like output.
- **Long session (200 actions):** near-neutral token impact (-1.6%). Compression savings from repeated reads are offset by overhead on short command outputs.
- **Source code:** STRICT_RAW by default. No structural compression without explicit `recoverable_lossy` policy. Summary mode available but requires agent to `expand()` for full source.

## Coverage

- **GPT-OSS 120B:** tested on 10/11 scenarios (90.9%). `long_session_200` excluded — 400 model calls prohibitive for 120B local inference.
- **DeepSeek v4 Pro:** full coverage — 11/11 scenarios.
- **Single run per scenario:** no statistical repeats. Quality delta reported as point estimate, not confidence interval.
- **Deterministic evaluation only:** quality measured via `expected_contains` matching, not LLM-as-judge. Open-ended answers not assessed.

## Performance

- **No concurrent write safety:** Artifact Store and Context Ledger use SQLite in WAL mode but are not tested under concurrent writes.
- **No resource limits:** no max input size, no output cap, no storage quota.
- **Token counting:** uses `tiktoken` (cl100k_base) for GPT-family models. Heuristic `len(text)//3` fallback for others. Not calibrated for DeepSeek/Qwen/Llama tokenizers.

## Security

- **No authentication on API:** FastAPI endpoints are unauthenticated (localhost-only by default).
- **Shell injection risk:** `squeeze_run_and_compress` uses `shell=True`. No command allowlist.
- **No path allowlist:** `squeeze_read_file` can read any file accessible to the process.
- **No log redaction:** raw content may appear in structured logs at DEBUG level.

## Operational

- **No automatic cleanup:** artifacts accumulate indefinitely in `~/.kettu-squeeze/`.
- **No schema migrations:** SQLite schema is created on first use. No migration path for future versions.
- **Single process:** no distributed deployment. MCP server shares engine instance in-process.

## Benchmark Methodology

- **Quality = expected_contains match:** recall measured as fraction of expected keywords found in model output. Not a comprehensive task success metric.
- **No blinding:** evaluator knows which mode (RAW/SQUEEZE) produced each output.
- **No adversarial eval:** compression not tested against intentionally misleading content.
