# Data Handling — Kettu Squeeze v0.1.0

## What data is stored

| Data | Location | Format | Retention |
|------|----------|--------|-----------|
| Raw tool outputs | `~/.kettu-squeeze/blobs/` | Binary (SHA-256 addressed) | Manual cleanup |
| Artifact metadata | `~/.kettu-squeeze/artifacts.db` | SQLite | Manual cleanup |
| Context ledger | `~/.kettu-squeeze/artifacts.db` | SQLite | Session-scoped |
| Compression stats | `~/.kettu-squeeze/artifacts.db` | SQLite (same DB) | Cumulative |
| Benchmark results | `benchmarks/results/` | JSONL | Git-tracked |
| Model responses (GPT-OSS) | Not stored | — | Ephemeral (not saved) |

## What data is NOT stored

- No telemetry
- No crash reports
- No usage analytics
- No model weights
- No API keys (except in benchmark configs — gitignore them)

## Data Flow

```
Tool output → classify → store raw blob → compress → verify → context ledger → agent
                                                           ↓ (on failure)
                                                        raw fallback
```

Raw blob is stored BEFORE compression. On verification failure, raw is returned — the compressed version is never shown to the agent.

## Privacy

- All processing is local
- No network calls (except MCP client connection to agent)
- No third-party services
- Air-gap compatible

## Cleanup

No automatic cleanup. To remove all data:

```bash
rm -rf ~/.kettu-squeeze/
```

To clear only benchmark artifacts:

```bash
rm -rf benchmarks/results/runs.jsonl
```
