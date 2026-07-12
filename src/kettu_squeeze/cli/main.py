"""
Kettu Squeeze CLI — Typer-based interface (v0.5.5).

Updated: explicit --compressor flag, routing info in output.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import (
    CompressionMode,
    CompressionRequest,
    SourceType,
)

app = typer.Typer(
    name="kettu-squeeze",
    help="Safe context compression for AI agents",
    no_args_is_help=True,
)

engine = SqueezeEngine()


# ── compress ─────────────────────────────────────────────────────────────────

@app.command()
def compress(
    path: Optional[str] = typer.Argument(
        None, help="File path to compress. Omit to read from stdin."
    ),
    mode: str = typer.Option(
        "lossless", "--mode", "-m",
        help="Compression mode: strict_raw, lossless, recoverable_lossy",
    ),
    source_type: str = typer.Option(
        "file", "--type", "-t",
        help="Source type: file, tool, command, api",
    ),
    compressor: Optional[str] = typer.Option(
        None, "--compressor", "-c",
        help="Explicit compressor override (e.g., json, git_diff, log, test_output, source_code, generic)",
    ),
    tokenizer: str = typer.Option(
        "gpt-oss", "--tokenizer", help="Tokenizer for estimation",
    ),
    session_id: str = typer.Option(
        "cli-session", "--session", help="Session ID",
    ),
    max_tokens: Optional[int] = typer.Option(
        None, "--max-tokens", help="Max output tokens",
    ),
    explain: bool = typer.Option(
        False, "--explain", "-x", help="Show routing decision explaining compressor choice",
    ),
):
    """Compress content from a file or stdin."""
    # Read content
    if path:
        content = Path(path).read_text()
        source_path = path
        st = SourceType(source_type) if source_type != "file" else SourceType.FILE
    else:
        content = sys.stdin.read()
        source_path = None
        st = SourceType(source_type)

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
        compressor=compressor,
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

    # Explain routing
    if explain and response.routing:
        typer.echo(f"# Routing: {response.routing.explain().replace(chr(10), ' | ')}")
        if response.routing.fallbacks_tried:
            typer.echo(f"# Fallbacks tried: {', '.join(response.routing.fallbacks_tried)}")

    typer.echo("---")
    typer.echo(response.content)


# ── expand ──────────────────────────────────────────────────────────────────

@app.command()
def expand(
    ref: str = typer.Argument(..., help="Reference to expand (e.g., artifact:uuid:L10-L50)"),
):
    """Expand a compressed reference back to original content."""
    from kettu_squeeze.types import ExpandRequest

    response = engine.expand(ExpandRequest(ref=ref))
    if response is None:
        typer.echo(f"✗ Reference not found: {ref}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"# Artifact: {response.artifact_id}")
    if response.line_range:
        typer.echo(f"# Range: {response.line_range}")
    typer.echo("---")
    typer.echo(response.content)


# ── inspect ──────────────────────────────────────────────────────────────────

@app.command()
def inspect(
    artifact_id: str = typer.Argument(..., help="Artifact ID to inspect"),
):
    """Show metadata for an artifact."""
    record = engine.store.get(artifact_id)
    if record is None:
        typer.echo(f"✗ Artifact not found: {artifact_id}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Artifact: {record.artifact_id}")
    typer.echo(f"  Source type: {record.source_type.value}")
    typer.echo(f"  Original size: {record.original_size} bytes")
    typer.echo(f"  Hash: {record.content_hash}")
    typer.echo(f"  Session: {record.session_id}")
    if record.source_path:
        typer.echo(f"  Source path: {record.source_path}")


# ── stats ────────────────────────────────────────────────────────────────────

@app.command()
def stats():
    """Show compression statistics."""
    count = engine.store.count()
    size = engine.store.total_size()
    typer.echo(f"Total artifacts: {count}")
    typer.echo(f"Total storage: {size} bytes ({size // 1024} KB)")


# ── doctor ───────────────────────────────────────────────────────────────────

@app.command()
def doctor():
    """Run system checks."""
    ok = True

    typer.echo("🔍 Kettu Squeeze Doctor")
    typer.echo("─" * 50)

    # Storage
    base = engine.store.base_dir
    typer.echo(f"  Storage directory: {base}")
    typer.echo(f"    {'✓' if base.exists() else '✗'} Storage directory exists")

    db_path = engine.store.db_path
    typer.echo(f"  Database: {db_path}")
    typer.echo(f"    {'✓' if db_path.exists() else '✗'} Database exists")

    blobs = base / "blobs"
    typer.echo(f"  Blob store: {blobs}")
    typer.echo(f"    {'✓' if blobs.exists() else '✗'} Blob directory exists")

    # tiktoken
    try:
        import tiktoken
        typer.echo("  tiktoken: ✓ available")
    except ImportError:
        typer.echo("  tiktoken: ✗ not installed")
        ok = False

    # Python
    v = sys.version_info
    if v >= (3, 11):
        typer.echo(f"  Python: ✓ {v.major}.{v.minor}.{v.micro}")
    else:
        typer.echo(f"  Python: ✗ {v.major}.{v.minor}.{v.micro} (need 3.11+)")
        ok = False

    typer.echo("─" * 50)
    if ok:
        typer.echo("✅ All checks passed")
    else:
        typer.echo("⚠ Some checks failed — review above")


if __name__ == "__main__":
    app()
