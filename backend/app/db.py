"""SQLite storage for chat sessions (standard library sqlite3 only)."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        """Create tables on startup (idempotent)."""
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def ping(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def get_history(self, session_id: str) -> list[dict]:
        """Messages as the LLM expects them, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def get_system_prompt(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row["system_prompt"] if row else None

    def get_messages(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        out = []
        for r in rows:
            item = {"role": r["role"], "content": r["content"]}
            if r["role"] == "assistant" and r["metadata"]:
                item["metadata"] = json.loads(r["metadata"])
            out.append(item)
        return out

    def save_exchange(
        self,
        session_id: str,
        user_message: str,
        reply: str,
        metadata: dict,
        system_prompt: str | None,
    ) -> None:
        """Store the user message and assistant reply atomically.

        Only called after a successful LLM answer, so failed requests
        (422 / 503) never touch the history.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, system_prompt, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt)",
                (session_id, system_prompt, _now()),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, 'user', ?, NULL, ?)",
                (session_id, user_message, _now()),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, 'assistant', ?, ?, ?)",
                (session_id, reply, json.dumps(metadata), _now()),
            )
