import json
import threading
import time
from pathlib import Path
from typing import Any

from .knowledge_service import KnowledgeService
from .knowledge_store import KnowledgeStore
from .memory_pipeline import MemoryPipeline


class TaskType:
    INGEST_MARKDOWN = "ingest_markdown"
    INGEST_HTML = "ingest_html"
    INGEST_URL = "ingest_url"
    INGEST_CONTRIBUTION = "ingest_contribution"
    UPDATE_DOCUMENT = "update_document"
    DELETE_DOCUMENT = "delete_document"
    REINDEX_DOCUMENT = "reindex_document"
    REBUILD_LONG_MEMORY = "rebuild_long_memory"


class TaskDispatcher:
    def __init__(
        self,
        store: KnowledgeStore,
        service: KnowledgeService,
        memory_pipeline: MemoryPipeline,
    ) -> None:
        self._store = store
        self._service = service
        self._memory_pipeline = memory_pipeline
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._run, name="knowledge-task-worker", daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._worker.start()
        self._started = True

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker.is_alive():
            self._worker.join(timeout=2)

    def enqueue(self, task_type: str, payload: dict[str, Any], document_id: int | None = None) -> int:
        task_id = self._store.create_task(
            task_type=task_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            document_id=document_id,
        )
        return task_id

    def pause_task(self, task_id: int) -> None:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        status = str(task.get("status") or "")
        if status not in {"pending", "running", "paused"}:
            raise ValueError("当前任务状态不支持暂停")
        message = "任务已暂停，等待继续"
        if status == "running":
            message = "已请求暂停，当前阶段结束后将停留在暂停状态"
        self._store.task_pause(task_id, message)

    def resume_task(self, task_id: int) -> None:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        if str(task.get("status") or "") != "paused":
            raise ValueError("只有暂停状态的任务可以继续")
        self._store.task_resume(task_id, "任务已继续")

    def delete_task(self, task_id: int) -> None:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        status = str(task.get("status") or "")
        if status == "running":
            raise ValueError("运行中的任务不能直接删除，请先暂停")
        self._store.delete_task(task_id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            task = self._store.get_next_pending_task()
            if not task:
                time.sleep(0.5)
                continue
            task_id = int(task["id"])
            try:
                self._store.task_mark_running(task_id, "任务开始执行")
                payload = json.loads(task.get("payload_json") or "{}")
                self._execute_task(task_id, str(task["task_type"]), payload, task.get("document_id"))
                self._store.task_mark_done(task_id, "任务执行成功")
            except Exception as exc:  # noqa: BLE001
                self._store.task_mark_failed(task_id, f"{type(exc).__name__}: {exc}")
            time.sleep(0.1)

    def _execute_task(
        self,
        task_id: int,
        task_type: str,
        payload: dict[str, Any],
        document_id: int | None,
    ) -> None:
        if task_type == TaskType.INGEST_MARKDOWN:
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 10, "开始解析 Markdown")
            filename = str(payload.get("filename") or "uploaded.md")
            content = str(payload.get("content") or "")
            source_type = str(payload.get("source_type") or "markdown")
            source_ref = str(payload.get("source_ref") or filename)
            title = str(payload.get("title") or filename)
            self._service.ingest_text(
                title=title,
                content=content,
                source_type=source_type,
                source_ref=source_ref,
            )
            self._store.task_update_progress(task_id, 100, "Markdown 入库并生成记忆完成")
            return

        if task_type == TaskType.INGEST_HTML:
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 10, "开始解析 HTML 邮件")
            filename = str(payload.get("filename") or "uploaded.html")
            content = str(payload.get("content") or "")
            description = str(payload.get("description") or "")
            base_dir = Path(str(payload.get("base_dir") or ".")).resolve()
            output_dir = base_dir / "data_html"
            document_id, output_path = self._service.ingest_html_email(
                filename,
                content,
                output_dir,
                description=description,
            )
            try:
                relative_path = output_path.relative_to(base_dir)
            except ValueError:
                relative_path = output_path
            self._store.task_update_progress(
                task_id,
                100,
                f"HTML 已解析为 Markdown，文档ID={document_id}，保存至 {relative_path}",
            )
            return

        if task_type == TaskType.INGEST_URL:
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 10, "开始抓取 URL")
            self._service.ingest_url(str(payload.get("url") or ""))
            self._store.task_update_progress(task_id, 100, "URL 入库并生成记忆完成")
            return

        if task_type == TaskType.INGEST_CONTRIBUTION:
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 10, "保存案例贡献")
            title = str(payload.get("title") or "case_contribution.md")
            source_ref = str(payload.get("source_ref") or title)
            content = str(payload.get("content") or "")
            base_dir = Path(str(payload.get("base_dir") or ".")).resolve()
            contributions_dir = base_dir / "data" / "contributions"
            contributions_dir.mkdir(parents=True, exist_ok=True)
            file_path = contributions_dir / title
            file_path.write_text(content, encoding="utf-8")
            source_ref = str(file_path.relative_to(base_dir))
            self._service.ingest_text(
                title=title,
                content=content,
                source_type="contribution",
                source_ref=source_ref,
            )
            self._store.task_update_progress(task_id, 100, "案例贡献入库并生成记忆完成")
            return

        if task_type == TaskType.UPDATE_DOCUMENT:
            if not document_id:
                raise ValueError("缺少 document_id")
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 20, "更新文档并重新切片")
            self._service.update_document(
                document_id=document_id,
                title=str(payload.get("title") or f"doc-{document_id}"),
                content=str(payload.get("content") or ""),
                source_ref=str(payload.get("source_ref") or f"doc-{document_id}"),
            )
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 80, "重建长期记忆")
            self._memory_pipeline.rebuild_long_memories_from_all_short()
            self._store.task_update_progress(task_id, 100, "文档更新完成")
            return

        if task_type == TaskType.DELETE_DOCUMENT:
            if not document_id:
                raise ValueError("缺少 document_id")
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 20, "删除文档与短期记忆")
            self._service.delete_document(document_id)
            rebuild_long = bool(payload.get("rebuild_long_memory"))
            if rebuild_long:
                self._wait_if_paused(task_id)
                self._store.task_update_progress(task_id, 80, "重建长期记忆")
                self._memory_pipeline.rebuild_long_memories_from_all_short()
                self._store.task_update_progress(task_id, 100, "文档删除完成，并已重建长期记忆")
                return
            self._store.task_update_progress(task_id, 100, "文档删除完成，未重建长期记忆")
            return

        if task_type == TaskType.REINDEX_DOCUMENT:
            if not document_id:
                raise ValueError("缺少 document_id")
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 20, "重新生成短期记忆")
            self._service.reindex_document(document_id)
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 80, "重建长期记忆")
            self._memory_pipeline.rebuild_long_memories_from_all_short()
            self._store.task_update_progress(task_id, 100, "重建完成")
            return

        if task_type == TaskType.REBUILD_LONG_MEMORY:
            self._wait_if_paused(task_id)
            self._store.task_update_progress(task_id, 20, "全量重建长期记忆")
            created = self._memory_pipeline.rebuild_long_memories_from_all_short()
            self._store.task_update_progress(task_id, 100, f"长期记忆重建完成，生成 {created} 条")
            return

        raise ValueError(f"不支持的任务类型: {task_type}")

    def _wait_if_paused(self, task_id: int) -> None:
        while not self._stop_event.is_set():
            task = self._store.get_task(task_id)
            if not task:
                raise ValueError("任务不存在或已删除")
            if str(task.get("status") or "") != "paused":
                return
            time.sleep(0.4)
