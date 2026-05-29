from dataclasses import dataclass

from .config import Settings
from .knowledge_store import KnowledgeStore


@dataclass(frozen=True)
class RetrievalResult:
    context: str
    source: str
    max_score: float
    has_email_case: bool


class KnowledgeRetriever:
    def __init__(self, store: KnowledgeStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    def retrieve(self, question: str) -> RetrievalResult:
        return self.retrieve_with_k(
            question=question,
            short_k=self._settings.short_memory_retrieval_k,
            long_k=self._settings.long_memory_retrieval_k,
            chunk_k=self._settings.chunk_retrieval_k,
        )

    def retrieve_with_k(self, question: str, short_k: int, long_k: int, chunk_k: int) -> RetrievalResult:
        short_items = self._store.search_short_memories(question, max(0, short_k))
        long_items = self._store.search_long_memories(question, max(0, long_k))
        chunk_items = self._store.search_chunks(question, max(0, chunk_k))

        blocks: list[str] = []
        max_score = 0.0
        has_email_case = False
        if long_items:
            lines = [f"- {item['summary']}" for item in long_items]
            blocks.append("【长期记忆】\n" + "\n".join(lines))
            max_score = max(max_score, max(float(item.get("_score") or 0.0) for item in long_items))
        if short_items:
            lines = [f"- {item['summary']} (来源: {item['source_ref']})" for item in short_items]
            blocks.append("【短期记忆】\n" + "\n".join(lines))
            max_score = max(max_score, max(float(item.get("_score") or 0.0) for item in short_items))
            has_email_case = has_email_case or any(_looks_like_email_case(str(item.get("summary") or "")) for item in short_items)
        if chunk_items:
            lines = [
                f"- {item['chunk_text']} (文档: {item['document_title']}#{item['chunk_index']})"
                for item in chunk_items
            ]
            blocks.append("【原文片段】\n" + "\n".join(lines))
            max_score = max(max_score, max(float(item.get("_score") or 0.0) for item in chunk_items))
            has_email_case = has_email_case or any(_looks_like_email_case(str(item.get("chunk_text") or "")) for item in chunk_items)

        context = "\n\n".join(blocks)
        source = "db" if max_score >= self._settings.db_hit_score_threshold and context.strip() else "none"
        return RetrievalResult(
            context=context,
            source=source,
            max_score=max_score,
            has_email_case=has_email_case,
        )


def _looks_like_email_case(text: str) -> bool:
    t = (text or "").lower()
    if "best regards" in t or "kind regards" in t:
        return True
    if "subject:" in t or "dear " in t:
        return True
    if "thank you" in t and "support" in t:
        return True
    if "邮件" in text and "回复" in text:
        return True
    return False
