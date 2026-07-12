"""
Kettu Squeeze — MCP Server.

Exposes 6 tools for AI agents:
  squeeze_compress        — Compress content through Kettu Squeeze
  squeeze_expand          — Expand a compressed reference
  squeeze_read_file       — Read and compress a file
  squeeze_run_and_compress — Run a shell command and compress its output
  squeeze_inspect_artifact — Get artifact metadata
  squeeze_context_status   — Show context ledger state

All tools require session_id, agent_id, conversation_id.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import (
    CompressionMode,
    CompressionRequest,
    ExpandRequest,
    SourceType,
)

# ── Server ───────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="Kettu Squeeze",
    instructions="""
Kettu Squeeze provides safe context compression for AI agents.

Principles:
- Raw is authoritative. Compression is a view, never the source of truth.
- Lossless by default. Lossy requires explicit policy.
- Session-aware. Storage cache ≠ model visibility.
- Every compressed output is verified.
- Any omission has a recoverable reference.
""",
)

engine = SqueezeEngine()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_mode(hint: str | None, source_path: str | None) -> CompressionMode:
    """Resolve compression mode based on hint and path."""
    if hint:
        try:
            return CompressionMode(hint)
        except ValueError:
            pass

    # Auto-detect: source code → strict_raw
    if source_path:
        ext = Path(source_path).suffix.lower()
        source_exts = {
            ".py", ".rs", ".js", ".ts", ".jsx", ".tsx", ".go",
            ".java", ".kt", ".c", ".cpp", ".h", ".hpp", ".rb",
            ".sh", ".bash", ".zsh",
        }
        config_exts = {".yaml", ".yml", ".toml", ".json", ".cfg", ".ini", ".conf"}
        if ext in source_exts or ext in config_exts:
            return CompressionMode.STRICT_RAW

    return CompressionMode.LOSSLESS


# ── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def squeeze_compress(
    content: str,
    session_id: str,
    agent_id: str,
    conversation_id: str = "default",
    source_type: str = "tool",
    source_path: str | None = None,
    mode: str | None = None,
    max_tokens: int | None = None,
) -> dict:
    """Compress content before it enters the LLM context.

    All content is first stored as an immutable artifact.
    Compression is verified — on failure, raw content is returned.
    Omitted blocks have recoverable references.

    Args:
        content: The raw text to compress.
        session_id: Current agent session ID.
        agent_id: Agent identifier (e.g., 'hermes', 'openclaw').
        conversation_id: Conversation/thread ID.
        source_type: 'file', 'tool', 'command', or 'api'.
        source_path: Optional path for the content source.
        mode: 'strict_raw', 'lossless', or 'recoverable_lossy'.
        max_tokens: Optional max output tokens.
    """
    st = SourceType(source_type)
    cm = _resolve_mode(mode, source_path)

    request = CompressionRequest(
        content=content,
        source_type=st,
        source_path=source_path,
        session_id=session_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        mode=cm,
        max_tokens=max_tokens,
    )

    response = engine.compress(request)

    result = {
        "content": response.content,
        "artifact_id": response.artifact_id,
        "mode": response.mode.value,
        "lossy": response.lossy,
        "recoverable": response.recoverable,
        "original_tokens": response.original_tokens,
        "compressed_tokens": response.compressed_tokens,
        "compression_ratio": response.compression_ratio,
    }

    if response.refs:
        result["refs"] = response.refs

    if not response.verification.passed:
        result["verification_warning"] = response.verification.fallback_reason
        result["verification_fallback"] = True

    return result


@mcp.tool()
def squeeze_expand(
    ref: str,
    session_id: str,
) -> dict:
    """Expand a compressed reference back to original content.

    Refs are of the form:
      artifact:<artifact_id>              — whole artifact
      artifact:<artifact_id>:L<start>-L<end>  — line range

    Args:
        ref: The reference string to expand.
        session_id: Current agent session ID (for access control).
    """
    request = ExpandRequest(ref=ref, session_id=session_id)
    result = engine.expand(request)

    if result is None:
        return {
            "error": f"Reference not found or invalid: {ref}",
            "ref": ref,
        }

    return {
        "ref": ref,
        "artifact_id": result.artifact_id,
        "content": result.content,
        "line_range": result.line_range,
        "size_bytes": len(result.content.encode("utf-8")),
    }


@mcp.tool()
def squeeze_read_file(
    path: str,
    session_id: str,
    agent_id: str,
    conversation_id: str = "default",
    mode: str | None = None,
) -> dict:
    """Read a file from disk and return its compressed contents.

    Source code files default to STRICT_RAW (no modification).
    All content is first stored as an immutable artifact.

    Args:
        path: Absolute or relative path to the file.
        session_id: Current agent session ID.
        agent_id: Agent identifier.
        conversation_id: Conversation/thread ID.
        mode: Compression mode override.
    """
    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        return {"error": f"File not found: {path}", "path": str(file_path)}

    try:
        content = file_path.read_text()
    except UnicodeDecodeError:
        return {"error": f"Cannot read file as text: {path}", "path": str(file_path)}
    except Exception as e:
        return {"error": str(e), "path": str(file_path)}

    cm = _resolve_mode(mode, str(file_path))

    request = CompressionRequest(
        content=content,
        source_type=SourceType.FILE,
        source_path=str(file_path),
        session_id=session_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        mode=cm,
    )

    response = engine.compress(request)

    return {
        "path": str(file_path),
        "content": response.content,
        "artifact_id": response.artifact_id,
        "mode": response.mode.value,
        "lossy": response.lossy,
        "original_tokens": response.original_tokens,
        "compressed_tokens": response.compressed_tokens,
        "compression_ratio": response.compression_ratio,
        "size_bytes": len(content.encode("utf-8")),
        "refs": response.refs if response.refs else [],
    }


@mcp.tool()
def squeeze_run_and_compress(
    command: str,
    session_id: str,
    agent_id: str,
    conversation_id: str = "default",
    mode: str | None = None,
    timeout: int = 30,
    workdir: str | None = None,
    source_path: str | None = None,
) -> dict:
    """Run a shell command and return compressed output.

    The command runs in a subprocess. Output is captured,
    stored as an artifact, and compressed.

    Args:
        command: Shell command to execute.
        session_id: Current agent session ID.
        agent_id: Agent identifier.
        conversation_id: Conversation/thread ID.
        mode: Compression mode override.
        timeout: Max execution time in seconds.
        workdir: Optional working directory.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "error": f"Command timed out after {timeout}s",
            "exit_code": -1,
        }
    except Exception as e:
        return {"command": command, "error": str(e), "exit_code": -1}

    output = result.stdout
    if result.stderr:
        # Combine stderr into output for compression
        if output:
            output += "\n" + result.stderr
        else:
            output = result.stderr

    if not output:
        output = f"(exit code: {result.returncode})"

    cm = _resolve_mode(mode, source_path)

    request = CompressionRequest(
        content=output,
        source_type=SourceType.COMMAND,
        source_path=source_path or command[:100],
        session_id=session_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        mode=cm,
    )

    response = engine.compress(request)

    return {
        "command": command,
        "exit_code": result.returncode,
        "content": response.content,
        "artifact_id": response.artifact_id,
        "mode": response.mode.value,
        "original_tokens": response.original_tokens,
        "compressed_tokens": response.compressed_tokens,
        "compression_ratio": response.compression_ratio,
        "refs": response.refs if response.refs else [],
    }


@mcp.tool()
def squeeze_inspect_artifact(
    artifact_id: str,
) -> dict:
    """Get metadata about a stored artifact.

    Args:
        artifact_id: The artifact UUID to inspect.
    """
    record = engine.store.get(artifact_id)

    if record is None:
        return {"error": f"Artifact not found: {artifact_id}"}

    return {
        "artifact_id": record.artifact_id,
        "content_hash": record.content_hash,
        "source_type": record.source_type.value,
        "source_path": record.source_path,
        "mime_type": record.mime_type,
        "session_id": record.session_id,
        "agent_id": record.agent_id,
        "created_at": record.created_at,
        "size_bytes": record.size_bytes,
        "version": record.version,
        "parent_artifact_id": record.parent_artifact_id,
    }


@mcp.tool()
def squeeze_context_status(
    session_id: str,
) -> dict:
    """Show what is currently visible in the context ledger.

    Args:
        session_id: The session to query.
    """
    entries = engine.get_context(session_id)

    return {
        "session_id": session_id,
        "visible_entries": len(entries),
        "total_estimated_tokens": sum(e.estimated_tokens for e in entries),
        "entries": [
            {
                "artifact_id": e.artifact_id,
                "content_hash": e.content_hash,
                "visibility": e.visibility.value,
                "estimated_tokens": e.estimated_tokens,
                "context_generation": e.context_generation,
            }
            for e in entries
        ],
    }


# ── Entry Point ──────────────────────────────────────────────────────────────

def main():
    """Run the MCP server (stdio transport)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
