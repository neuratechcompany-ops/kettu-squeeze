"""
Kettu Squeeze CLI — Typer-based command line interface.

Usage:
    kettu-squeeze compress file.log
    kettu-squeeze compress --mode lossless file.json
    kettu-squeeze expand "artifact:uuid:L10-L50"
    kettu-squeeze inspect <artifact-id>
    kettu-squeeze stats
    kettu-squeeze doctor
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import (
    CompressionMode,
    CompressionRequest,
    ExpandRequest,
    SourceType,
)

app = typer.Typer(
    name="kettu-squeeze",
    help="Safe context compression for AI agents",
    no_args_is_help=True,
)

engine = SqueezeEngine()


# ── Compress ────────────────────────────────────────────────────────────────


@app.command()
def compress(
    path: Optional[str] = typer.Argument(
        None, help="File path to compress. Omit to read from stdin."
    ),
    mode: str = typer.Option(
        "lossless",
        "--mode",
        "-m",
        help="Compression mode: strict_raw, lossless, recoverable_lossy",
    ),
    source_type: str = typer.Option(
        "file", "--type", "-t", help="Source type: file, tool, command, api"
    ),
    tokenizer: str = typer.Option(
        "gpt-oss", "--tokenizer", help="Tokenizer for estimation"
    ),
    session_id: str = typer.Option(
        "cli-session", "--session", help="Session ID"
    ),
    max_tokens: Optional[int] = typer.Option(
        None, "--max-tokens", help="Max output tokens"
    ),
):
    """Compress content from a file or stdin."""
    # Read content
    if path:
        content = Path(path).read_text()
        source_path = path
        st = SourceType.FILE
    else:
        content = sys.stdin.read()
        source_path = None
        st = SourceType(source_type)  # Use --type flag, don't override

    cm = CompressionMode(mode)

    request = CompressionRequest(
        content=content,
        source_type=st,
        source_path=source_path,
        session_id=session_id,
        agent_id="cli",
        mode=cm,
        tokenizer=tokenizer,
        max_tokens=max_tokens,
    )

    response = engine.compress(request)

    # Output
    if not response.verification.passed:
        typer.echo(
            f"⚠ Verification failed: {response.verification.fallback_reason}",
            err=True,
        )

    typer.echo(f"# Artifact: {response.artifact_id}")
    typer.echo(f"# Mode: {response.mode.value} Lossy: {response.lossy}")
    typer.echo(
        f"# Tokens: {response.original_tokens} → {response.compressed_tokens} "
        f"({response.compression_ratio:.1f}x)"
    )
    typer.echo("---")
    typer.echo(response.content)


# ── Expand ──────────────────────────────────────────────────────────────────


@app.command()
def expand(
    ref: str = typer.Argument(..., help="Reference to expand (e.g., artifact:uuid:L10-L50)"),
):
    """Expand a compressed reference back to original content."""
    request = ExpandRequest(ref=ref, session_id="cli-session")
    result = engine.expand(request)

    if result is None:
        typer.echo(f"Error: Reference not found: {ref}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"# Artifact: {result.artifact_id}")
    if result.line_range:
        typer.echo(f"# Range: {result.line_range}")
    typer.echo("---")
    typer.echo(result.content)


# ── Inspect ─────────────────────────────────────────────────────────────────


@app.command()
def inspect(
    artifact_id: str = typer.Argument(..., help="Artifact ID to inspect"),
):
    """Show metadata for an artifact."""
    record = engine.store.get(artifact_id)
    if record is None:
        typer.echo(f"Error: Artifact not found: {artifact_id}", err=True)
        raise typer.Exit(code=1)

    typer.echo(json.dumps(record.model_dump(), indent=2, default=str))


# ── Stats ───────────────────────────────────────────────────────────────────


@app.command()
def stats():
    """Show compression statistics."""
    import sqlite3

    db_path = engine.store.db_path
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Count artifacts
    total_artifacts = conn.execute(
        "SELECT COUNT(*) as c FROM artifacts"
    ).fetchone()["c"]

    total_size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) as c FROM artifacts"
    ).fetchone()["c"]

    total_sessions = conn.execute(
        "SELECT COUNT(DISTINCT session_id) as c FROM artifacts"
    ).fetchone()["c"]

    # Context ledger stats
    total_entries = conn.execute(
        "SELECT COUNT(*) as c FROM context_ledger"
    ).fetchone()["c"]

    active_entries = conn.execute(
        "SELECT COUNT(*) as c FROM context_ledger WHERE active = 1"
    ).fetchone()["c"]

    conn.close()

    typer.echo("📊 Kettu Squeeze Stats")
    typer.echo("─" * 50)
    typer.echo(f"  Total artifacts:     {total_artifacts}")
    typer.echo(f"  Total size:          {_format_bytes(total_size)}")
    typer.echo(f"  Sessions:            {total_sessions}")
    typer.echo(f"  Context entries:     {total_entries}")
    typer.echo(f"  Active in context:   {active_entries}")


# ── Doctor ──────────────────────────────────────────────────────────────────


@app.command()
def doctor():
    """Run system checks."""
    ok = True

    typer.echo("🔍 Kettu Squeeze Doctor")
    typer.echo("─" * 50)

    # Check storage
    store_dir = engine.store.base_dir
    typer.echo(f"  Storage directory: {store_dir}")
    if store_dir.exists():
        typer.echo("    ✓ Storage directory exists")
    else:
        typer.echo("    ✗ Storage directory missing")
        ok = False

    # Check DB
    db_path = engine.store.db_path
    typer.echo(f"  Database: {db_path}")
    if db_path.exists():
        typer.echo("    ✓ Database exists")
    else:
        typer.echo("    ✗ Database missing")
        ok = False

    # Check blobs
    blob_dir = engine.store.blob_dir
    typer.echo(f"  Blob store: {blob_dir}")
    if blob_dir.exists():
        typer.echo("    ✓ Blob directory exists")
    else:
        typer.echo("    ✗ Blob directory missing")
        ok = False

    # Check tiktoken
    try:
        import tiktoken
        typer.echo("  tiktoken: ✓ available")
    except ImportError:
        typer.echo("  tiktoken: ⚠ not installed (token estimates will be approximate)")
        ok = False

    # Check Python version
    version = sys.version_info
    if version >= (3, 12):
        typer.echo(f"  Python: ✓ {version.major}.{version.minor}.{version.micro}")
    else:
        typer.echo(f"  Python: ✗ {version.major}.{version.minor}.{version.micro} (need 3.12+)")
        ok = False

    typer.echo("─" * 50)
    if ok:
        typer.echo("✅ All checks passed")
    else:
        typer.echo("⚠ Some checks failed — review above")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _format_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


if __name__ == "__main__":
    app()
