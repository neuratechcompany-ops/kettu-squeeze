"""
Kettu Squeeze — FastAPI server.

Provides REST API for compress, expand, context management, health, and metrics.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    REGISTRY,
)

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import (
    CompressionRequest,
    CompressionResponse,
    ContextEntry,
    ExpandRequest,
    ExpandResponse,
    VerificationResult,
)


# ── Metrics ──────────────────────────────────────────────────────────────────

requests_total = Counter(
    "squeeze_requests_total",
    "Total compression requests",
    ["endpoint"],
)

failures_total = Counter(
    "squeeze_failures_total",
    "Total verification failures",
)

fallback_raw_total = Counter(
    "squeeze_fallback_raw_total",
    "Total fallback-to-raw events",
)

tokens_original = Counter(
    "squeeze_tokens_original_total",
    "Total original tokens",
)

tokens_compressed = Counter(
    "squeeze_tokens_output_total",
    "Total output tokens",
)

refs_expanded_total = Counter(
    "squeeze_refs_expanded_total",
    "Total refs expanded",
)

latency_histogram = Histogram(
    "squeeze_latency_seconds",
    "Compression latency in seconds",
)


# ── App Setup ────────────────────────────────────────────────────────────────

engine: SqueezeEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global engine
    engine = SqueezeEngine()
    yield


app = FastAPI(
    title="Kettu Squeeze",
    version="0.1.0",
    description="Safe context compression for AI agents",
    lifespan=lifespan,
)


def get_engine() -> SqueezeEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return engine


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    eng = get_engine()
    # Check DB connectivity
    try:
        eng.store.get("nonexistent")
    except Exception:
        pass
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return generate_latest(REGISTRY)


@app.post("/v1/compress", response_model=CompressionResponse)
async def compress(request: CompressionRequest):
    requests_total.labels(endpoint="compress").inc()
    try:
        with latency_histogram.time():
            eng = get_engine()
            response = eng.compress(request)

        tokens_original.inc(response.original_tokens)
        tokens_compressed.inc(response.compressed_tokens)

        if not response.verification.passed:
            failures_total.inc()
        if response.verification.warnings:
            fallback_raw_total.inc()

        return response
    except Exception as e:
        failures_total.inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/expand", response_model=ExpandResponse)
async def expand(request: ExpandRequest):
    requests_total.labels(endpoint="expand").inc()
    eng = get_engine()
    result = eng.expand(request)
    if result is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    refs_expanded_total.inc()
    return result


@app.post("/v1/artifacts")
async def store_artifact(
    content: str,
    source_type: str = "tool",
    source_path: str | None = None,
    session_id: str = "default",
    agent_id: str = "default",
):
    requests_total.labels(endpoint="artifacts").inc()
    eng = get_engine()
    from kettu_squeeze.types import SourceType
    from kettu_squeeze.classifier import classifier

    st = SourceType(source_type)
    classification = classifier.classify(content, st, source_path)
    artifact = eng.store.store(content, classification, session_id, agent_id)
    return {"artifact_id": artifact.artifact_id}


@app.get("/v1/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    requests_total.labels(endpoint="get_artifact").inc()
    eng = get_engine()
    record = eng.store.get(artifact_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return record.model_dump()


@app.get("/v1/artifacts/{artifact_id}/range")
async def get_artifact_range(
    artifact_id: str, start_line: int, end_line: int
):
    requests_total.labels(endpoint="get_range").inc()
    eng = get_engine()
    blob = eng.store.get_range(artifact_id, start_line, end_line)
    if blob is None:
        raise HTTPException(status_code=404, detail="Artifact or range not found")
    return {"content": blob.decode("utf-8")}


@app.post("/v1/context/register")
async def register_context(
    session_id: str,
    agent_id: str,
    conversation_id: str,
    artifact_id: str,
    content_hash: str,
    visibility: str = "full",
    estimated_tokens: int = 0,
):
    requests_total.labels(endpoint="register_context").inc()
    eng = get_engine()
    from kettu_squeeze.types import Visibility

    entry = eng.register_visible(
        session_id=session_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        content_hash=content_hash,
        visibility=Visibility(visibility),
        estimated_tokens=estimated_tokens,
    )
    return entry.model_dump()


@app.post("/v1/context/evict")
async def evict_context(
    session_id: str, artifact_id: str | None = None
):
    requests_total.labels(endpoint="evict_context").inc()
    eng = get_engine()
    if artifact_id:
        eng.evict(session_id, artifact_id)
    else:
        eng.evict_all(session_id)
    return {"status": "ok"}


@app.get("/v1/context/{session_id}")
async def get_context(session_id: str):
    requests_total.labels(endpoint="get_context").inc()
    eng = get_engine()
    entries = eng.get_context(session_id)
    return {"entries": [e.model_dump() for e in entries]}


@app.post("/v1/verify")
async def verify_representation(
    compressed: str,
    original: str,
    artifact_id: str,
    session_id: str = "default",
    agent_id: str = "default",
):
    requests_total.labels(endpoint="verify").inc()
    eng = get_engine()
    from kettu_squeeze.types import CompressionPolicy, CompressionMode
    from kettu_squeeze.verifier import verifier

    artifact = eng.store.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    policy = CompressionPolicy(source_type="*", mode=CompressionMode.LOSSLESS)
    result = verifier.verify(compressed, original, artifact, policy)
    return result.model_dump()
