from .config import Settings
from .knowledge_store import KnowledgeStore
from .llm_client import LLMClient, LLMRequestError


class MemoryPipeline:
    def __init__(self, store: KnowledgeStore, llm_client: LLMClient, settings: Settings) -> None:
        self._store = store
        self._llm = llm_client
        self._settings = settings

    def on_document_ingested(self, document_id: int, chunks: list[str], source_ref: str) -> None:
        if not self._settings.enable_memory_pipeline or not chunks:
            return
        short_memories: list[tuple[int, str, str]] = []
        for idx, chunk in enumerate(chunks):
            text = chunk.strip()
            if not text:
                continue
            try:
                summary = self._llm.summarize_short_memory(text)
            except LLMRequestError:
                continue
            short_memories.append((idx, summary, f"{source_ref}#chunk{idx}"))

        self._store.add_short_memories(document_id, short_memories)
        self._store.prune_short_memories(self._settings.short_memory_max_items)
        self._maybe_build_long_memory()

    def _maybe_build_long_memory(self) -> None:
        trigger = max(1, self._settings.long_memory_trigger_size)
        total = self._store.count_short_memories()
        if total == 0 or total % trigger != 0:
            return
        recent = self._store.get_recent_short_memories(trigger)
        if not recent:
            return
        block = "\n".join(f"- {item['summary']}" for item in reversed(recent))
        source_refs = ", ".join(sorted({str(item["source_ref"]) for item in recent}))
        try:
            summary = self._llm.summarize_long_memory(block)
        except LLMRequestError:
            return
        self._store.add_long_memory(summary=summary, source_refs=source_refs)

    def rebuild_long_memories_from_all_short(self) -> int:
        if not self._settings.enable_memory_pipeline:
            return 0
        batch_size = max(1, self._settings.long_memory_trigger_size)
        short_items = self._store.get_recent_short_memories(self._settings.short_memory_max_items)
        if not short_items:
            self._store.clear_long_memories()
            return 0

        ordered = list(reversed(short_items))
        self._store.clear_long_memories()
        created = 0
        for i in range(0, len(ordered), batch_size):
            batch = ordered[i : i + batch_size]
            block = "\n".join(f"- {item['summary']}" for item in batch)
            source_refs = ", ".join(sorted({str(item["source_ref"]) for item in batch}))
            try:
                summary = self._llm.summarize_long_memory(block)
            except LLMRequestError:
                continue
            self._store.add_long_memory(summary=summary, source_refs=source_refs)
            created += 1
        return created
