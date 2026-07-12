"""
Context Ledger — tracks what the model has actually seen.

Separate from storage cache. Persistent cache hit does NOT imply visibility.
Ref is valid only if the artifact is registered as visible in the current session.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from kettu_squeeze.types import ContextEntry, Visibility


class ContextLedger:
    """Session-scoped registry of what the LLM has seen.

    Uses the same SQLite DB as ArtifactStore (table: context_ledger).
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    # ── Registration ────────────────────────────────────────────────────

    def register(
        self,
        session_id: str,
        agent_id: str,
        conversation_id: str,
        artifact_id: str,
        representation_id: str,
        content_hash: str,
        visibility: Visibility,
        estimated_tokens: int,
    ) -> ContextEntry:
        """Record that the model has seen this artifact representation."""
        inserted_at = datetime.now(timezone.utc).isoformat()
        generation = self.next_generation(session_id)

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO context_ledger
                   (session_id, agent_id, conversation_id, artifact_id,
                    representation_id, content_hash, visibility, inserted_at,
                    estimated_tokens, context_generation, active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    session_id,
                    agent_id,
                    conversation_id,
                    artifact_id,
                    representation_id,
                    content_hash,
                    visibility.value,
                    inserted_at,
                    estimated_tokens,
                    generation,
                ),
            )

        return ContextEntry(
            session_id=session_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            representation_id=representation_id,
            content_hash=content_hash,
            visibility=visibility,
            inserted_at=inserted_at,
            estimated_tokens=estimated_tokens,
            context_generation=generation,
            active=True,
        )

    def evict(self, session_id: str, artifact_id: str) -> None:
        """Mark an entry as no longer visible (evicted from context window)."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE context_ledger
                   SET active = 0
                   WHERE session_id = ? AND artifact_id = ? AND active = 1""",
                (session_id, artifact_id),
            )

    def evict_all(self, session_id: str) -> None:
        """Mark all entries as evicted for a session (e.g., session reset)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE context_ledger SET active = 0 WHERE session_id = ?",
                (session_id,),
            )

    # ── Queries ─────────────────────────────────────────────────────────

    def is_visible(self, session_id: str, content_hash: str) -> bool:
        """Check if content_hash is currently visible to the model."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM context_ledger
                   WHERE session_id = ?
                     AND content_hash = ?
                     AND active = 1
                   LIMIT 1""",
                (session_id, content_hash),
            ).fetchone()
        return row is not None

    def is_artifact_visible(self, session_id: str, artifact_id: str) -> bool:
        """Check if a specific artifact_id is visible."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM context_ledger
                   WHERE session_id = ?
                     AND artifact_id = ?
                     AND active = 1
                   LIMIT 1""",
                (session_id, artifact_id),
            ).fetchone()
        return row is not None

    def get_visible(self, session_id: str) -> list[ContextEntry]:
        """Get all visible entries for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM context_ledger
                   WHERE session_id = ? AND active = 1
                   ORDER BY context_generation ASC""",
                (session_id,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_visible_hashes(self, session_id: str) -> set[str]:
        """Get set of visible content hashes for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT content_hash FROM context_ledger
                   WHERE session_id = ? AND active = 1""",
                (session_id,),
            ).fetchall()
        return {r["content_hash"] for r in rows}

    def next_generation(self, session_id: str) -> int:
        """Get the next monotonic generation number for a session."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COALESCE(MAX(context_generation), 0) + 1 AS next
                   FROM context_ledger
                   WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
        return row["next"]

    def get_entry(self, session_id: str, artifact_id: str) -> ContextEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM context_ledger
                   WHERE session_id = ? AND artifact_id = ? AND active = 1
                   LIMIT 1""",
                (session_id, artifact_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _row_to_entry(self, row: sqlite3.Row) -> ContextEntry:
        return ContextEntry(
            id=row["id"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            conversation_id=row["conversation_id"],
            artifact_id=row["artifact_id"],
            representation_id=row["representation_id"],
            content_hash=row["content_hash"],
            visibility=Visibility(row["visibility"]),
            inserted_at=row["inserted_at"],
            estimated_tokens=row["estimated_tokens"],
            context_generation=row["context_generation"],
            active=bool(row["active"]),
        )
