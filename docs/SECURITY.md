# Security — Kettu Squeeze v0.1.0

## Threat Model

See `docs/THREAT_MODEL.md` for all identified attack vectors (AV-1 through AV-10).

## Security Properties

| Property | Status | Enforcement |
|----------|--------|-------------|
| Raw artifact immutability | ✅ | Append-only store, no delete API |
| Every omission recoverable | ✅ | `[omitted: N lines, ref=artifact:...]` format |
| Session isolation | ✅ | Context ledger scoped by session_id |
| No cross-session refs | ✅ | `is_visible()` check per session |
| Unicode crash-free | ✅ | Character-boundary operations, property tests |
| Verifier on all paths | ✅ | engine.compress → verifier.verify mandatory |
| Fallback to raw on failure | ✅ | `if not verification.passed: return raw` |
| No silent lossy mode | ✅ | `lossy: true` in response, `lossy_marked` verifier check |
| Prompt injection resistance | ⚠️ | Ref format uses structured `artifact:UUID` — not regex-parsed from user content |
| Secret leakage prevention | ⚠️ | No log redaction of raw content by default |

## Data Storage

- **Location:** `~/.kettu-squeeze/`
- **Database:** SQLite WAL mode, `artifacts.db`
- **Blobs:** Content-addressed under `blobs/<hash[0:2]>/<full_hash>`
- **Permissions:** Inherited from user's `~/.kettu-squeeze/` directory
- **Cleanup:** Manual only. No automatic data retention policy yet.

## MCP Security

- **Transport:** stdio (default) or HTTP (FastAPI)
- **Authentication:** None by default. MCP runs as local process.
- **Shell execution:** `squeeze_run_and_compress` uses `subprocess.run(shell=True)`. Command is provided by the agent. No allowlist. Known risk.
- **File access:** `squeeze_read_file` reads any path accessible to the process. No path allowlist.
- **Input validation:** Pydantic models on API. MCP tools use type hints.

## API Security (FastAPI)

- **Authentication:** None (localhost-only by default)
- **Rate limiting:** None
- **CORS:** Not configured
- **Metrics:** Prometheus on `/metrics` — no authentication
- **Health:** `/health` and `/ready` — public

## Recommendations for Production Use

1. Add path allowlist for `squeeze_read_file`
2. Replace `shell=True` with `shell=False` + argv array
3. Add output size cap for `squeeze_run_and_compress`
4. Add authentication to FastAPI endpoints
5. Add rate limiting
6. Implement log redaction for raw content
7. Add data retention policy and cleanup
8. Add `.gitignore` for `~/.kettu-squeeze/` artifacts
