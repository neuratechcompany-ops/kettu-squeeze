"""
Artifact Store — immutable, append-only storage for raw content.

Uses SQLite for metadata + filesystem for blob storage.
Content-addressed: same content → same blob (storage-level dedup).
Different source_path → different artifact record (provenance preserved).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kettu_squeeze.types import ArtifactRecord, ClassificationResult


class ArtifactStore:
    """Immutable storage for raw artifacts.

    Blob layout: <base_dir>/blobs/<first_two_hex>/<full_sha256>
    Metadata: <base_dir>/artifacts.db (SQLite)
    """

    def __init__(self, base_dir: str | Path = "~/.kettu-squeeze"):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.blob_dir = self.base_dir / "blobs"
        self.db_path = self.base_dir / "artifacts.db"
        self._ensure_dirs()
        self._init_db()

    # ── Initialization ──────────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.blob_dir.mkdir(parents=True, exist_ok=True)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id    TEXT PRIMARY KEY,
                    content_hash   TEXT NOT NULL,
                    source_type    TEXT NOT NULL,
                    source_path    TEXT,
                    mime_type      TEXT NOT NULL DEFAULT 'text/plain',
                    encoding       TEXT NOT NULL DEFAULT 'utf-8',
                    session_id     TEXT NOT NULL,
                    agent_id       TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    size_bytes     INTEGER NOT NULL DEFAULT 0,
                    blob_path      TEXT NOT NULL,
                    parent_artifact_id TEXT,
                    version        INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS context_ledger (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id         TEXT NOT NULL,
                    agent_id           TEXT NOT NULL,
                    conversation_id    TEXT NOT NULL,
                    artifact_id        TEXT NOT NULL,
                    representation_id  TEXT NOT NULL,
                    content_hash       TEXT NOT NULL,
                    visibility         TEXT NOT NULL,
                    inserted_at        TEXT NOT NULL,
                    estimated_tokens   INTEGER NOT NULL DEFAULT 0,
                    context_generation INTEGER NOT NULL DEFAULT 0,
                    active             INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_hash
                    ON artifacts(content_hash);
                CREATE INDEX IF NOT EXISTS idx_artifacts_session
                    ON artifacts(session_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_path
                    ON artifacts(source_path);
                CREATE INDEX IF NOT EXISTS idx_ledger_session
                    ON context_ledger(session_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_artifact
                    ON context_ledger(artifact_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_hash_active
                    ON context_ledger(content_hash, active);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    # ── Hash & path helpers ─────────────────────────────────────────────

    @staticmethod
    def compute_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _blob_path_for(self, content_hash: str) -> Path:
        return self.blob_dir / content_hash[:2] / content_hash

    # ── Core operations ─────────────────────────────────────────────────

    def store(
        self,
        content: str,
        classification: ClassificationResult,
        session_id: str,
        agent_id: str,
        parent_artifact_id: str | None = None,
    ) -> ArtifactRecord:
        """Store raw content as an immutable artifact.

        Args:
            content: Raw content string.
            classification: Metadata from the classifier.
            session_id: Current agent session.
            agent_id: Agent identifier.
            parent_artifact_id: For delta source.

        Returns:
            ArtifactRecord with the stored metadata.
        """
        content_bytes = content.encode("utf-8")
        content_hash = self.compute_hash(content_bytes)
        blob_path = self._blob_path_for(content_hash)
        blob_rel = str(blob_path.relative_to(self.base_dir))

        # Atomic blob write: write to temp, then rename
        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(blob_path.parent))
            try:
                with os.fdopen(tmp_fd, "wb") as f:
                    f.write(content_bytes)
                os.rename(tmp_path, str(blob_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        # Insert metadata record
        created_at = datetime.now(timezone.utc).isoformat()
        record = ArtifactRecord(
            content_hash=content_hash,
            source_type=classification.source_type,
            source_path=classification.source_path,
            mime_type=classification.mime_type,
            encoding=classification.encoding,
            session_id=session_id,
            agent_id=agent_id,
            created_at=created_at,
            size_bytes=classification.size_bytes,
            blob_path=blob_rel,
            parent_artifact_id=parent_artifact_id,
        )

        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO artifacts
                       (artifact_id, content_hash, source_type, source_path,
                        mime_type, encoding, session_id, agent_id, created_at,
                        size_bytes, blob_path, parent_artifact_id, version)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record.artifact_id,
                        record.content_hash,
                        record.source_type.value,
                        record.source_path,
                        record.mime_type,
                        record.encoding,
                        record.session_id,
                        record.agent_id,
                        record.created_at,
                        record.size_bytes,
                        record.blob_path,
                        record.parent_artifact_id,
                        record.version,
                    ),
                )
            except sqlite3.IntegrityError:
                # artifact already exists — idempotent
                pass

        return record

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_hash(self, content_hash: str) -> ArtifactRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_blob(self, artifact_id: str) -> bytes | None:
        record = self.get(artifact_id)
        if record is None:
            return None
        return self._read_blob(record)

    def get_range(
        self, artifact_id: str, start_line: int, end_line: int
    ) -> bytes | None:
        """Get a line range from an artifact (1-indexed, inclusive)."""
        record = self.get(artifact_id)
        if record is None:
            return None
        blob = self._read_blob(record)
        if blob is None:
            return None
        text = blob.decode("utf-8")
        lines = text.splitlines(keepends=True)
        if start_line < 1:
            start_line = 1
        if end_line > len(lines):
            end_line = len(lines)
        if start_line > end_line:
            return b""
        return "".join(lines[start_line - 1 : end_line]).encode("utf-8")

    def exists(self, content_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM artifacts WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return row is not None

    # ── Helpers ─────────────────────────────────────────────────────────

    def _read_blob(self, record: ArtifactRecord) -> bytes | None:
        blob_path = self.base_dir / record.blob_path
        if not blob_path.exists():
            return None
        return blob_path.read_bytes()

    def _row_to_record(self, row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            content_hash=row["content_hash"],
            source_type=row["source_type"],
            source_path=row["source_path"],
            mime_type=row["mime_type"],
            encoding=row["encoding"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            created_at=row["created_at"],
            size_bytes=row["size_bytes"],
            blob_path=row["blob_path"],
            parent_artifact_id=row["parent_artifact_id"],
            version=row["version"],
        )
