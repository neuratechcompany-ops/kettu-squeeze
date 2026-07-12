# Kettu Squeeze — Agent Skill

## Purpose

Use Kettu Squeeze to compress large tool outputs before passing them to the model. This preserves critical facts (errors, IDs, paths, exit codes) while reducing token consumption.

## When to Use

- Tool output exceeds configurable threshold (recommended: 200 tokens)
- Repeated file reads, test runs, or container logs
- Large JSON API responses with repeated structure
- Docker/Kubernetes diagnostics
- Context window near budget limit

## When NOT to Use

- Payload is small (<100 tokens)
- Full verbatim text required
- Cryptographic material or secrets
- Unsupported binary data
- No Artifact Store available for externalized data

## Algorithm

1. Detect the agent's current task from the goal/context
2. Pass task goal + tool command + payload to Kettu Squeeze
3. Use ADAPTIVE mode for task-aware compression
4. Pass only `model_facing_content` to the model
5. Store the result ID for potential recovery
6. If model needs more detail, use selective expand (single hunk, traceback frame, JSON path)

## Usage

```python
from kettu_squeeze.bulk.engine import bulk_compact

result = bulk_compact(tool_output, critical_facts=["error_code", "container_id"])
# result is the compressed, model-facing content
```

## Selective Expand

```python
# Recover a specific log incident, traceback frame, or JSON path
# without expanding the entire artifact
```

## Examples

See `skills/kettu-squeeze/scripts/` for ready-to-use scripts:

- `compress_context.py` — compress tool output with task awareness
- `expand_reference.py` — selective expand from artifact reference
- `inspect_result.py` — show compression details and stats

## Compatible With

- Hermes Agent
- OpenClaw-style local agents
- Python-based agents
- Shell tool pipelines
