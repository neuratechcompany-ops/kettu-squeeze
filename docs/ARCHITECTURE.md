# Kettu Squeeze — Architecture v0.1.0

## Overview

Kettu Squeeze is a local, safe context optimization layer for AI agents.
It compresses tool outputs, logs, JSON, test reports, and large data before
they enter the LLM context window — without irreversibly deleting critical information.

## Design Philosophy

1. **Raw is authoritative.** Compression is a view, never the source of truth.
2. **Lossless by default.** Lossy requires explicit policy and recoverable refs.
3. **Session-aware.** Storage cache ≠ model visibility. Context ledger tracks what the model actually saw.
4. **Verify everything.** Every compressed output passes through a verifier.
5. **Fall back safely.** On any violation: return raw.

## Data Flow

```text
Tool / File / Command Output
            │
            ▼
     ┌──────────────┐
     │  Classifier   │  Determines source_type, mime_type, encoding
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │   Artifact    │  Saves immutable raw blob + metadata record
     │   Registry    │
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │  Structural   │  Normalizes without losing information
     │  Normalizer   │  (strip ANSI, normalize whitespace)
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │  Compression  │  Routes to appropriate compressor
     │    Router     │  based on source_type + policy
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │   Verifier    │  Checks invariants, refs, content preservation
     └──────┬───────┘
            │
       ┌────┴────┐
       ▼         ▼
    PASS       FAIL
       │         │
       ▼         ▼
   Compressed   RAW
   Output       Output
       │
       ▼
     ┌──────────────┐
     │   Context     │  Registers representation as visible to model
     │   Ledger      │
     └──────┬───────┘
            │
            ▼
       Agent / LLM

Recovery path:

  Agent → expand(ref) → Artifact Registry → raw fragment
```

## Component Details

### 1. Input Classifier (`src/classifier/`)

Determines metadata about incoming content without modifying it.

**Input:** raw bytes or string
**Output:** ClassificationResult

```python
@dataclass
class ClassificationResult:
    source_type: Literal["file", "tool", "command", "api"]
    source_path: str | None        # e.g., "/project/src/auth.py"
    mime_type: str                  # e.g., "text/x-python"
    encoding: str                   # "utf-8"
    size_bytes: int
    is_unicode_safe: bool
```

**Logic:**
- If `source_path` provided → use extension-based MIME detection
- If tool name provided → classify by tool type
- Fallback: content sniffing (JSON starts with `{` or `[`, etc.)

### 2. Artifact Registry (`src/artifact_store/`)

Immutable, append-only storage for all raw content.

**Schema:**
```sql
CREATE TABLE artifacts (
    artifact_id    TEXT PRIMARY KEY,     -- UUID
    content_hash   TEXT NOT NULL,        -- SHA-256 hex
    source_type    TEXT NOT NULL,
    source_path    TEXT,
    mime_type      TEXT NOT NULL,
    encoding       TEXT NOT NULL DEFAULT 'utf-8',
    session_id     TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    created_at     TEXT NOT NULL,        -- ISO-8601
    size_bytes     INTEGER NOT NULL,
    blob_path      TEXT NOT NULL,        -- relative to blob store root
    parent_artifact_id TEXT,            -- for delta source
    version        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_artifacts_hash ON artifacts(content_hash);
CREATE INDEX idx_artifacts_session ON artifacts(session_id);
CREATE INDEX idx_artifacts_path ON artifacts(source_path);
```

**Blob Storage:**
- Content-addressed: `blobs/<first_two_hex>/<full_hash>`
- Same content → same blob (dedup at storage level)
- Different paths → different artifact records (different artifact_id)
- Atomic writes via temp file + rename

**API:**
```python
class ArtifactStore:
    def store(self, content: bytes, classification: ClassificationResult,
              session_id: str, agent_id: str) -> ArtifactRecord: ...
    def get(self, artifact_id: str) -> ArtifactRecord: ...
    def get_blob(self, artifact_id: str) -> bytes: ...
    def get_range(self, artifact_id: str, start_line: int, end_line: int) -> bytes: ...
    def exists(self, content_hash: str) -> bool: ...
```

### 3. Context Ledger (`src/context_ledger/`)

Tracks what the model has actually seen. Separate from storage cache.

**Schema:**
```sql
CREATE TABLE context_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT NOT NULL,
    agent_id           TEXT NOT NULL,
    conversation_id    TEXT NOT NULL,
    artifact_id        TEXT NOT NULL,
    representation_id  TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    visibility         TEXT NOT NULL,        -- 'full', 'summary', 'delta', 'reference'
    inserted_at        TEXT NOT NULL,
    estimated_tokens   INTEGER NOT NULL,
    context_generation INTEGER NOT NULL,     -- monotonic counter per session
    active             INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_ledger_session ON context_ledger(session_id);
CREATE INDEX idx_ledger_artifact ON context_ledger(artifact_id);
CREATE INDEX idx_ledger_hash_active ON context_ledger(content_hash, active);
```

**API:**
```python
class ContextLedger:
    def register(self, session_id: str, agent_id: str, conversation_id: str,
                 artifact_id: str, representation_id: str, content_hash: str,
                 visibility: str, estimated_tokens: int) -> ContextEntry: ...
    def evict(self, session_id: str, artifact_id: str) -> None: ...
    def is_visible(self, session_id: str, content_hash: str) -> bool: ...
    def get_visible(self, session_id: str) -> list[ContextEntry]: ...
    def next_generation(self, session_id: str) -> int: ...
```

**Rules:**
- `is_visible()` returns True only if `active=1` for the given session_id
- Evicted entries set `active=0` — not deleted (audit trail)
- New session starts with empty active ledger
- Storage cache hit does NOT imply visibility

### 4. Compression Router (`src/compressors/`)

Routes content to the appropriate compressor.

**Modes:**

| Mode | Description | Default For |
|------|-------------|-------------|
| `strict_raw` | No compression (ANSI strip only) | source code, configs, SQL, small files, unknown |
| `lossless` | Information-preserving compression | logs, JSON, test outputs, git diff |
| `recoverable_lossy` | Removes parts but ALL are recoverable via refs | Large logs (>10K lines), verbose API responses |

**Compressor Registry:**

```python
COMPRESSORS = {
    "log": LogCompressor,
    "json": JsonCompressor,
    "test_output": TestOutputCompressor,
    "git_diff": GitDiffCompressor,
    "source_code": SourceCodeCompressor,  # strict_raw by default
    "generic": GenericCompressor,          # lossless only
}
```

**Routing Logic:**
```python
def route(self, artifact: ArtifactRecord, content: str, policy: CompressionPolicy):
    if policy.mode == "strict_raw":
        return self.strip_ansi(content)
    compressor = self.COMPRESSORS.get(artifact.source_type, GenericCompressor)
    return compressor.compress(content, artifact, policy)
```

### 5. Compressors

#### 5.1 Log Compressor (`log_compressor.py`)

**Lossless operations:**
- Strip ANSI escape codes
- Normalize timestamp formats (preserve values)
- Merge identical consecutive lines with counter (RLE):
  ```
  ERROR connection refused
  ERROR connection refused
  ERROR connection refused
  ```
  →
  ```
  ERROR connection refused ×3
  ```

**Recoverable Lossy (explicit policy only):**
- Keep first N and last M lines + error lines
- Replace middle with `[omitted: 423 lines, ref=artifact#L200-L623]`

#### 5.2 JSON Compressor (`json_compressor.py`)

**Lossless operations:**
- Compact encoding (no extra whitespace)
- Sort keys deterministically
- Remove null fields (configurable)

**Recoverable Lossy (explicit policy only):**
- Repeated objects in arrays → template + count
- Large arrays → head/tail/sample with refs
- Deep nesting → flatten to depth N with `[nested: ref=...]` markers

#### 5.3 Test Output Compressor (`test_compressor.py`)

- Parse test framework output (pytest, go test, cargo test, jest)
- Keep: summary (PASSED/FAILED counts), ALL failures with full trace
- Aggregate: passed tests → "✓ 147 passed"
- Exit code always preserved
- Stack traces: collapse framework frames, keep user code frames

#### 5.4 Git Diff Compressor (`diff_compressor.py`)

- Keep: file list, hunk headers, changed lines
- Aggregate: identical hunks across files
- Full patch available via ref

#### 5.5 Source Code Compressor (`source_compressor.py`)

**strict_raw by default.** No structural changes without explicit policy.

**Allowed with `lossless` policy:**
- Strip ANSI
- Normalize trailing whitespace

**Allowed with explicit `summary` policy:**
- Symbol index (functions, classes, imports)
- File outline
- Each section has recoverable ref to full source

### 6. Verifier (`src/verifier/`)

Runs on every compressed output before it reaches the agent.

```python
class VerificationResult:
    passed: bool
    checks: list[CheckResult]
    fallback_reason: str | None
```

**Checks:**
1. `utf8_validity`: output is valid UTF-8
2. `refs_exist`: every `[omitted: ... ref=...]` points to existing artifact
3. `refs_valid`: line ranges are within artifact bounds, hash matches
4. `exit_code_preserved`: if input had exit code, output has it
5. `errors_preserved`: error messages not truncated
6. `paths_preserved`: file paths intact
7. `identifiers_preserved`: function/class names present
8. `urls_preserved`: URLs unmodified
9. `json_valid`: if output claims JSON, it parses
10. `delta_target_hash`: delta reconstructs to correct hash
11. `non_empty`: result is not empty
12. `no_broken_refs`: all refs resolve
13. `lossy_marked`: if content was modified, `lossy=true` is set

**On failure:**
```python
if not result.passed:
    logger.warning("Verification failed", reason=result.fallback_reason)
    metrics.increment("squeeze_fallback_raw_total")
    return raw_content
```

### 7. Expand System

Reverse of compression. Agent calls `expand(ref)` to get original content.

**Ref Format:**
```
artifact:<artifact_id>:L<start>-L<end>
artifact:<artifact_id>           # whole artifact
hash:<content_hash>              # by hash
```

**Implementation:**
```python
def expand(self, ref: str, session_id: str) -> bytes:
    parsed = parse_ref(ref)
    artifact = self.artifact_store.get(parsed.artifact_id)
    if parsed.line_range:
        return self.artifact_store.get_range(
            parsed.artifact_id, parsed.start_line, parsed.end_line
        )
    return self.artifact_store.get_blob(parsed.artifact_id)
```

### 8. API Layer (`src/api/`)

FastAPI server with following endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/compress` | Compress content |
| POST | `/v1/expand` | Expand a reference |
| POST | `/v1/artifacts` | Store raw artifact |
| GET | `/v1/artifacts/{id}` | Get artifact metadata |
| GET | `/v1/artifacts/{id}/range` | Get byte range |
| POST | `/v1/context/register` | Register in context ledger |
| POST | `/v1/context/evict` | Evict from context ledger |
| GET | `/v1/context/{session_id}` | Get visible entries |
| POST | `/v1/verify` | Verify a representation |
| GET | `/health` | Health check |
| GET | `/ready` | Readiness check |
| GET | `/metrics` | Prometheus metrics |

**Compress Request:**
```json
{
  "content": "...",
  "source_type": "tool",
  "source_path": "pytest",
  "session_id": "session-123",
  "agent_id": "hermes",
  "conversation_id": "conv-456",
  "mode": "lossless",
  "tokenizer": "gpt-oss",
  "max_tokens": 4000
}
```

**Compress Response:**
```json
{
  "artifact_id": "uuid",
  "representation_id": "uuid",
  "mode": "lossless",
  "lossy": false,
  "recoverable": true,
  "original_tokens": 15400,
  "compressed_tokens": 3200,
  "compression_ratio": 4.81,
  "content": "...",
  "refs": [],
  "verification": {
    "passed": true,
    "warnings": []
  }
}
```

### 9. CLI (`src/cli/`)

```bash
kettu-squeeze compress file.log
kettu-squeeze compress --mode lossless file.json
kettu-squeeze compress --tokenizer gpt-oss output.txt
kettu-squeeze expand "artifact:uuid:L10-L50"
kettu-squeeze inspect <artifact-id>
kettu-squeeze verify <representation-id>
kettu-squeeze stats
kettu-squeeze doctor
```

### 10. Storage Layout

```
~/.kettu-squeeze/
├── artifacts.db          # SQLite with artifact metadata + context ledger
├── blobs/                # Content-addressed raw storage
│   ├── a1/
│   │   └── a1b2c3d4...   # full SHA-256 as filename
│   └── ...
└── config.toml           # Optional configuration overrides
```

### 11. Integration with Hermes (MCP)

MCP tools exposed:

```
squeeze_compress       — compress content, return artifact_id
squeeze_expand         — expand a reference
squeeze_read_file      — read file through squeeze
squeeze_run_and_compress — run command + compress output
squeeze_inspect_artifact — get artifact metadata
squeeze_context_status — show context ledger state
```

### 12. Dependencies

```
python >= 3.12
fastapi
uvicorn
pydantic >= 2.0
typer
structlog
prometheus-client
tiktoken
mcp >= 1.0
pytest
pytest-asyncio
hypothesis
```

## Sequence: Full Compression Flow

```
1. Agent calls squeeze_compress(content, source_type, source_path, session_id, ...)
2. API → Classifier.classify(content, source_type, source_path)
3. API → ArtifactStore.store(content, classification, session_id, agent_id)
4. API → StructuralNormalizer.normalize(content, classification)
5. API → CompressionRouter.route(normalized, classification, policy)
6. API → Verifier.verify(compressed, artifact, policy)
7. If verification fails → return raw content
8. API → ContextLedger.register(artifact_id, representation_id, session_id, ...)
9. Return compressed response to agent
```

## Sequence: Expand Flow

```
1. Agent calls squeeze_expand(ref, session_id)
2. API → parse_ref(ref)
3. API → ArtifactStore.get_range(artifact_id, start, end)
4. Return raw bytes to agent
```
