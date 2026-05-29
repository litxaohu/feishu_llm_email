import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .html_email_parser import HtmlEmailParser
from .knowledge_store import KnowledgeStore
from .memory_pipeline import MemoryPipeline


@dataclass(frozen=True)
class IngestConfig:
    chunk_size: int = 800
    chunk_overlap: int = 100
    request_timeout_seconds: int = 20


class KnowledgeService:
    def __init__(
        self,
        store: KnowledgeStore,
        config: IngestConfig | None = None,
        memory_pipeline: MemoryPipeline | None = None,
    ) -> None:
        self._store = store
        self._config = config or IngestConfig()
        self._memory_pipeline = memory_pipeline
        self._html_email_parser = HtmlEmailParser()

    def ingest_markdown(self, filename: str, content: str) -> int:
        title = Path(filename).name or "uploaded.md"
        return self.ingest_text(title=title, content=content, source_type="markdown", source_ref=title)

    def ingest_text(
        self,
        title: str,
        content: str,
        source_type: str,
        source_ref: str,
        build_memory: bool = True,
        status: str | None = None,
    ) -> int:
        cleaned = self._clean_text(content)
        document_id = self._store.create_document(
            title=title.strip() or "untitled",
            source_type=source_type,
            source_ref=source_ref.strip() or title.strip() or "untitled",
            status=status or ("processing" if build_memory else "saved"),
            content=cleaned,
        )
        if build_memory:
            self._finalize_document(document_id, cleaned)
        return document_id

    def save_markdown_document(self, title: str, content: str, source_ref: str) -> int:
        return self.ingest_text(
            title=title,
            content=content,
            source_type="markdown",
            source_ref=source_ref,
            build_memory=False,
            status="saved",
        )

    def ingest_html_email(
        self,
        filename: str,
        html: str,
        output_dir: Path,
        description: str = "",
    ) -> tuple[int, Path]:
        parsed = self._html_email_parser.parse(filename=filename, html=html, description=description)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / parsed.markdown_filename
        output_path.write_text(parsed.markdown_content, encoding="utf-8")
        document_id = self.save_markdown_document(
            title=parsed.title,
            content=parsed.markdown_content,
            source_ref=str(output_path),
        )
        return document_id, output_path

    def reindex_document(self, document_id: int) -> None:
        doc = self._store.get_document(document_id)
        if not doc:
            raise ValueError("文档不存在")
        content = self._clean_text(str(doc.get("content") or ""))
        self._store.update_document(
            document_id=document_id,
            title=str(doc.get("title") or f"doc-{document_id}"),
            content=content,
            source_ref=str(doc.get("source_ref") or f"doc-{document_id}"),
        )
        self._store.clear_short_memories_by_document(document_id)
        self._finalize_document(document_id, content)

    def update_document(self, document_id: int, title: str, content: str, source_ref: str) -> None:
        cleaned = self._clean_text(content)
        if not cleaned:
            raise ValueError("内容不能为空")
        self._store.update_document(
            document_id=document_id,
            title=title.strip() or f"doc-{document_id}",
            content=cleaned,
            source_ref=source_ref.strip() or f"doc-{document_id}",
        )
        self._store.clear_short_memories_by_document(document_id)
        self._finalize_document(document_id, cleaned)

    def delete_document(self, document_id: int) -> None:
        self._store.delete_document(document_id)

    def ingest_url(self, url: str) -> int:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("URL 必须以 http:// 或 https:// 开头")

        doc_id = self._store.create_document(
            title=url,
            source_type="url",
            source_ref=url,
            status="processing",
            content="",
        )
        try:
            response = requests.get(
                url,
                timeout=self._config.request_timeout_seconds,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    )
                },
            )
            response.raise_for_status()
            text = self._extract_main_text(response.text)
            cleaned = self._clean_text(text)
            self._store.set_document_result(doc_id, status="processing", chunk_count=0)
            self._store.update_document_content(doc_id, cleaned)
            self._finalize_document(doc_id, cleaned)
            return doc_id
        except Exception as exc:
            self._store.set_document_result(
                doc_id,
                status="failed",
                chunk_count=0,
                error_message=str(exc),
            )
            raise

    def _finalize_document(self, document_id: int, content: str) -> None:
        chunks = self._chunk_text(content)
        self._store.replace_chunks(document_id, chunks)
        self._store.bump_short_memory_rebuild_count(document_id)
        self._store.set_document_result(
            document_id,
            status="ready",
            chunk_count=len(chunks),
            error_message=None,
        )
        if self._memory_pipeline:
            doc = self._store.get_document(document_id)
            source_ref = (doc or {}).get("source_ref", f"doc-{document_id}")
            self._memory_pipeline.on_document_ingested(
                document_id=document_id,
                chunks=chunks,
                source_ref=str(source_ref),
            )

    def _chunk_text(self, text: str) -> list[str]:
        if not text:
            return []

        chunk_size = self._config.chunk_size
        overlap = min(self._config.chunk_overlap, max(chunk_size - 1, 0))
        chunks: list[str] = []
        start = 0
        total = len(text)
        while start < total:
            end = min(start + chunk_size, total)
            piece = text[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= total:
                break
            start = max(end - overlap, start + 1)
        return chunks

    @staticmethod
    def _extract_main_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n")

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
