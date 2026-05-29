import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    lark_app_id: str
    lark_app_secret: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: int
    llm_max_retries: int
    llm_retry_backoff_seconds: float
    llm_max_tokens: int
    llm_system_prompt: str
    max_user_question_chars: int
    knowledge_db_path: str
    enable_memory_pipeline: bool
    short_memory_max_items: int
    long_memory_trigger_size: int
    short_memory_retrieval_k: int
    long_memory_retrieval_k: int
    chunk_retrieval_k: int
    db_hit_score_threshold: float
    enable_web_search: bool
    web_search_max_results: int
    email_context_max_chars: int
    email_short_memory_retrieval_k: int
    email_long_memory_retrieval_k: int
    email_chunk_retrieval_k: int
    email_split_bilingual: bool
    enable_thinking_hint: bool
    thinking_hint_text: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        lark_app_id=_require_env("LARK_APP_ID"),
        lark_app_secret=_require_env("LARK_APP_SECRET"),
        llm_api_key=_require_env("LLM_API_KEY"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        llm_retry_backoff_seconds=float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "1.5")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "900")),
        llm_system_prompt=os.getenv(
            "LLM_SYSTEM_PROMPT",
            "你是企业内部飞书机器人助手，请提供准确、简洁、友好的回答。",
        ),
        max_user_question_chars=int(os.getenv("MAX_USER_QUESTION_CHARS", "2000")),
        knowledge_db_path=os.getenv("KNOWLEDGE_DB_PATH", "data/knowledge.db"),
        enable_memory_pipeline=_get_bool("ENABLE_MEMORY_PIPELINE", True),
        short_memory_max_items=int(os.getenv("SHORT_MEMORY_MAX_ITEMS", "300")),
        long_memory_trigger_size=int(os.getenv("LONG_MEMORY_TRIGGER_SIZE", "30")),
        short_memory_retrieval_k=int(os.getenv("SHORT_MEMORY_RETRIEVAL_K", "4")),
        long_memory_retrieval_k=int(os.getenv("LONG_MEMORY_RETRIEVAL_K", "2")),
        chunk_retrieval_k=int(os.getenv("CHUNK_RETRIEVAL_K", "3")),
        db_hit_score_threshold=float(os.getenv("DB_HIT_SCORE_THRESHOLD", "0.20")),
        enable_web_search=_get_bool("ENABLE_WEB_SEARCH", False),
        web_search_max_results=int(os.getenv("WEB_SEARCH_MAX_RESULTS", "3")),
        email_context_max_chars=int(os.getenv("EMAIL_CONTEXT_MAX_CHARS", "2500")),
        email_short_memory_retrieval_k=int(os.getenv("EMAIL_SHORT_MEMORY_RETRIEVAL_K", "2")),
        email_long_memory_retrieval_k=int(os.getenv("EMAIL_LONG_MEMORY_RETRIEVAL_K", "1")),
        email_chunk_retrieval_k=int(os.getenv("EMAIL_CHUNK_RETRIEVAL_K", "1")),
        email_split_bilingual=_get_bool("EMAIL_SPLIT_BILINGUAL", True),
        enable_thinking_hint=_get_bool("ENABLE_THINKING_HINT", True),
        thinking_hint_text=os.getenv(
            "THINKING_HINT_TEXT", "收到，正在思考中，请稍等..."
        ),
    )


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
