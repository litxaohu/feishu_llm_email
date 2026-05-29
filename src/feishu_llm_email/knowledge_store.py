import sqlite3
from pathlib import Path
from typing import Any
import re


class KnowledgeStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL,
                    error_message TEXT,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id)
                );

                CREATE TABLE IF NOT EXISTS short_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id)
                );

                CREATE TABLE IF NOT EXISTS long_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary TEXT NOT NULL,
                    source_refs TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS knowledge_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    document_id INTEGER,
                    payload_json TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME,
                    finished_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._ensure_columns(conn)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(knowledge_documents)").fetchall()
        }
        if "short_memory_rebuild_count" not in columns:
            conn.execute(
                """
                ALTER TABLE knowledge_documents
                ADD COLUMN short_memory_rebuild_count INTEGER NOT NULL DEFAULT 0
                """
            )

    def create_document(
        self,
        title: str,
        source_type: str,
        source_ref: str,
        status: str,
        content: str,
        error_message: str | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_documents
                    (title, source_type, source_ref, status, content, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, source_type, source_ref, status, content, error_message),
            )
            return int(cursor.lastrowid)

    def set_document_result(
        self,
        document_id: int,
        status: str,
        chunk_count: int,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, chunk_count = ?, error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, chunk_count, error_message, document_id),
            )

    def update_document_content(self, document_id: int, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_documents
                SET content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content, document_id),
            )

    def update_document(self, document_id: int, title: str, content: str, source_ref: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_documents
                SET title = ?, content = ?, source_ref = ?, status = 'processing',
                    error_message = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, content, source_ref, document_id),
            )

    def bump_short_memory_rebuild_count(self, document_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_documents
                SET short_memory_rebuild_count = short_memory_rebuild_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (document_id,),
            )

    def delete_document(self, document_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM short_memories WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))

    def replace_chunks(self, document_id: int, chunks: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            conn.executemany(
                """
                INSERT INTO knowledge_chunks (document_id, chunk_index, chunk_text)
                VALUES (?, ?, ?)
                """,
                [(document_id, index, text) for index, text in enumerate(chunks)],
            )

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 50,
        source_type: str = "",
        rebuild_count: int | None = None,
        title_keyword: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        where_clauses: list[str] = []
        args: list[Any] = []
        if source_type:
            where_clauses.append("source_type = ?")
            args.append(source_type)
        if rebuild_count is not None:
            where_clauses.append("short_memory_rebuild_count = ?")
            args.append(rebuild_count)
        if title_keyword.strip():
            where_clauses.append("title LIKE ?")
            args.append(f"%{title_keyword.strip()}%")
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        offset = max(0, (max(page, 1) - 1) * max(page_size, 1))
        with self._connect() as conn:
            total_row = conn.execute(
                f"""
                SELECT COUNT(1) AS c
                FROM knowledge_documents
                {where_sql}
                """,
                args,
            ).fetchone()
            rows = conn.execute(
                """
                SELECT id, title, source_type, source_ref, status, chunk_count, error_message,
                       short_memory_rebuild_count,
                       created_at, updated_at
                FROM knowledge_documents
                """
                + f"{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*args, max(page_size, 1), offset],
            ).fetchall()
        total = int(total_row["c"]) if total_row else 0
        return [dict(row) for row in rows], total

    def get_document_filter_options(self) -> dict[str, list[Any]]:
        with self._connect() as conn:
            source_rows = conn.execute(
                """
                SELECT DISTINCT source_type
                FROM knowledge_documents
                ORDER BY source_type ASC
                """
            ).fetchall()
            rebuild_rows = conn.execute(
                """
                SELECT DISTINCT short_memory_rebuild_count
                FROM knowledge_documents
                ORDER BY short_memory_rebuild_count ASC
                """
            ).fetchall()
        return {
            "source_types": [row["source_type"] for row in source_rows if row["source_type"]],
            "rebuild_counts": [row["short_memory_rebuild_count"] for row in rebuild_rows],
        }

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, source_type, source_ref, status, content, chunk_count,
                       error_message, short_memory_rebuild_count, created_at, updated_at
                FROM knowledge_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
            if row is None:
                return None

            chunks = conn.execute(
                """
                SELECT chunk_index, chunk_text
                FROM knowledge_chunks
                WHERE document_id = ?
                ORDER BY chunk_index ASC
                """,
                (document_id,),
            ).fetchall()

        data = dict(row)
        data["chunks"] = [dict(chunk) for chunk in chunks]
        return data

    def add_short_memories(
        self, document_id: int, summaries: list[tuple[int, str, str]]
    ) -> None:
        if not summaries:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO short_memories (document_id, chunk_index, summary, source_ref)
                VALUES (?, ?, ?, ?)
                """,
                [(document_id, idx, text, src) for idx, text, src in summaries],
            )

    def count_short_memories(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(1) AS c FROM short_memories").fetchone()
        return int(row["c"]) if row else 0

    def get_recent_short_memories(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, document_id, chunk_index, summary, source_ref, created_at
                FROM short_memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune_short_memories(self, keep_latest: int) -> None:
        if keep_latest <= 0:
            return
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM short_memories
                WHERE id NOT IN (
                    SELECT id FROM short_memories
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (keep_latest,),
            )

    def add_long_memory(self, summary: str, source_refs: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO long_memories (summary, source_refs)
                VALUES (?, ?)
                """,
                (summary, source_refs),
            )
            return int(cursor.lastrowid)

    def clear_long_memories(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM long_memories")

    def clear_short_memories_by_document(self, document_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM short_memories WHERE document_id = ?", (document_id,))

    def list_long_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, summary, source_refs, created_at
                FROM long_memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_short_memories(self, query: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, summary, source_ref, created_at
                FROM short_memories
                ORDER BY id DESC
                LIMIT 300
                """
            ).fetchall()
        return self._rank_rows(rows, query, "summary", limit, extra_keys=["source_ref"])

    def search_long_memories(self, query: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, summary, source_refs, created_at
                FROM long_memories
                ORDER BY id DESC
                LIMIT 200
                """
            ).fetchall()
        return self._rank_rows(rows, query, "summary", limit, extra_keys=["source_refs"])

    def search_chunks(self, query: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT kc.id, kc.document_id, kc.chunk_index, kc.chunk_text,
                       kd.title AS document_title
                FROM knowledge_chunks kc
                JOIN knowledge_documents kd ON kd.id = kc.document_id
                ORDER BY kc.id DESC
                LIMIT 600
                """
            ).fetchall()
        return self._rank_rows(
            rows, query, "chunk_text", limit, extra_keys=["document_id", "chunk_index", "document_title"]
        )

    def create_task(
        self,
        task_type: str,
        payload_json: str,
        document_id: int | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_tasks (task_type, document_id, payload_json, status, progress)
                VALUES (?, ?, ?, 'pending', 0)
                """,
                (task_type, document_id, payload_json),
            )
            return int(cursor.lastrowid)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, task_type, document_id, payload_json, status, progress, message,
                       created_at, started_at, finished_at, updated_at
                FROM knowledge_tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_task(self, task_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM knowledge_tasks WHERE id = ?", (task_id,))

    def list_tasks(self, page: int = 1, page_size: int = 10) -> tuple[list[dict[str, Any]], int]:
        offset = max(0, (max(page, 1) - 1) * max(page_size, 1))
        with self._connect() as conn:
            total_row = conn.execute("SELECT COUNT(1) AS c FROM knowledge_tasks").fetchone()
            rows = conn.execute(
                """
                SELECT id, task_type, document_id, status, progress, message,
                       created_at, started_at, finished_at, updated_at
                FROM knowledge_tasks
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (max(page_size, 1), offset),
            ).fetchall()
        total = int(total_row["c"]) if total_row else 0
        return [dict(row) for row in rows], total

    def get_next_pending_task(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, task_type, document_id, payload_json, status, progress, message
                FROM knowledge_tasks
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def task_mark_running(self, task_id: int, message: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_tasks
                SET status = 'running', progress = 1, message = ?, started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message, task_id),
            )

    def task_pause(self, task_id: int, message: str = "任务已暂停") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_tasks
                SET status = 'paused', message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('pending', 'running', 'paused')
                """,
                (message, task_id),
            )

    def task_resume(self, task_id: int, message: str = "任务已继续") -> None:
        task = self.get_task(task_id)
        if not task:
            return
        status = "running" if task.get("started_at") and not task.get("finished_at") else "pending"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_tasks
                SET status = ?, message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'paused'
                """,
                (status, message, task_id),
            )

    def task_update_progress(self, task_id: int, progress: int, message: str = "") -> None:
        p = max(0, min(100, progress))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_tasks
                SET progress = ?, message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (p, message, task_id),
            )

    def task_mark_done(self, task_id: int, message: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_tasks
                SET status = 'succeeded', progress = 100, message = ?, finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message, task_id),
            )

    def task_mark_failed(self, task_id: int, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_tasks
                SET status = 'failed', message = ?, finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message, task_id),
            )

    def _rank_rows(
        self,
        rows: list[sqlite3.Row],
        query: str,
        text_key: str,
        limit: int,
        extra_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query)
        ranked: list[tuple[float, dict[str, Any]]] = []
        keep_keys = [text_key]
        if extra_keys:
            keep_keys.extend(extra_keys)
        for row in rows:
            row_data = dict(row)
            text = str(row_data.get(text_key) or "")
            score = _overlap_score(query_tokens, _tokenize(text))
            if score <= 0:
                continue
            item = {k: row_data.get(k) for k in keep_keys}
            item["_score"] = score
            ranked.append((score, item))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in ranked[: max(0, limit)]]


def _tokenize(text: str) -> set[str]:
    text = (text or "").lower().strip()
    if not text:
        return set()
    # For Chinese content, a lightweight char-level tokenization works
    # better than whitespace split.
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    word_tokens = re.findall(r"[a-z0-9_]{2,}", text)
    return set(cjk_chars + word_tokens)


def _overlap_score(query_tokens: set[str], text_tokens: set[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = query_tokens.intersection(text_tokens)
    if not overlap:
        return 0.0
    return len(overlap) / max(1, len(query_tokens))
