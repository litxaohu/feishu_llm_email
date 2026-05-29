import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from lark_oapi.channel import FeishuChannel

from .config import Settings
from .knowledge_store import KnowledgeStore
from .llm_client import LLMClient, LLMRequestError
from .retriever import KnowledgeRetriever
from .task_dispatcher import TaskType
from .web_search import DuckDuckGoSearch

logger = logging.getLogger(__name__)


class FeishuLLMBot:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm_client = LLMClient(settings)
        base_dir = Path(__file__).resolve().parents[2]
        self._store = KnowledgeStore(base_dir / settings.knowledge_db_path)
        self._retriever = KnowledgeRetriever(self._store, settings)
        self._base_dir = base_dir
        self._web_search = DuckDuckGoSearch()
        self._channel = FeishuChannel(
            app_id=settings.lark_app_id,
            app_secret=settings.lark_app_secret,
        )
        self._register_handlers()

    async def run(self) -> None:
        logger.info("启动飞书长连接服务")
        await self._channel.connect()

    def _register_handlers(self) -> None:
        async def on_message(msg) -> None:
            question = (getattr(msg, "content_text", "") or "").strip()
            logger.info("收到消息，chat_id=%s, text_len=%s", getattr(getattr(msg, "conversation", None), "chat_id", None), len(question))
            if not question:
                await self._reply(msg, "我暂时只支持文本消息，请发送文本内容。")
                return

            if len(question) > self._settings.max_user_question_chars:
                await self._reply(
                    msg,
                    f"问题过长（>{self._settings.max_user_question_chars} 字），请精简后再试。",
                )
                return

            if question.startswith("[案例贡献]") or question.startswith("【案例贡献】"):
                await self._handle_contribution(msg, question)
                return

            if question.startswith("[邮件]") or question.startswith("【邮件】"):
                await self._handle_email(msg, question)
                return

            if self._settings.enable_thinking_hint:
                await self._reply(msg, self._settings.thinking_hint_text)

            try:
                retrieval = await asyncio.to_thread(self._retriever.retrieve, question)
                if retrieval.source == "db":
                    answer = await asyncio.to_thread(self._llm_client.ask, question, retrieval.context)
                    await self._reply(msg, f"【来源：数据库】\n\n{answer}")
                    return

                if self._settings.enable_web_search:
                    results = await asyncio.to_thread(
                        self._web_search.search, question, self._settings.web_search_max_results
                    )
                    if results:
                        lines = []
                        for r in results:
                            snippet = f"{r.snippet}" if r.snippet else ""
                            lines.append(f"- {r.title}\n  {snippet}\n  {r.url}")
                        web_context = "【互联网检索结果】\n" + "\n".join(lines)
                        answer = await asyncio.to_thread(self._llm_client.ask, question, web_context)
                        await self._reply(msg, f"【来源：互联网】\n\n{answer}")
                        return

                answer = await asyncio.to_thread(self._llm_client.ask, question)
                await self._reply(msg, f"【来源：模型】\n\n{answer}")
            except LLMRequestError as exc:
                logger.warning("调用大模型失败: %s", exc.user_message)
                await self._reply(msg, exc.user_message)
                return
            except Exception:
                logger.exception("调用大模型失败")
                await self._reply(msg, "调用模型失败，请稍后重试。")
                return

        self._channel.on("message", on_message)

    async def _reply(self, msg, text: str) -> None:
        text = text.strip() or "收到消息，但当前没有可返回内容。"
        chat_id = getattr(getattr(msg, "conversation", None), "chat_id", None)
        if not chat_id:
            logger.warning("消息缺少 chat_id，无法回复")
            return
        await self._channel.send(chat_id, {"text": text})

    async def _handle_contribution(self, msg, raw: str) -> None:
        content = raw.replace("[案例贡献]", "", 1).replace("【案例贡献】", "", 1).strip()
        if not content:
            await self._reply(msg, "请在 [案例贡献] 后粘贴要贡献的内容。")
            return
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = f"case_contribution_{now}.md"
        md = (
            f"# 案例贡献 {now}\n\n"
            f"## 原始内容\n\n"
            f"{content}\n"
        )
        task_id = self._store.create_task(
            task_type=TaskType.INGEST_CONTRIBUTION,
            payload_json=json.dumps(
                {"title": title, "source_ref": title, "content": md, "base_dir": str(self._base_dir)},
                ensure_ascii=False,
            ),
            document_id=None,
        )
        await self._reply(msg, f"已收到案例贡献，后台处理中，任务ID={task_id}。请在管理后台查看进度与结果。")

    async def _handle_email(self, msg, raw: str) -> None:
        email_text = raw.replace("[邮件]", "", 1).replace("【邮件】", "", 1).strip()
        if not email_text:
            await self._reply(msg, "请在 [邮件] 后粘贴要回复的邮件原文。")
            return

        if self._settings.enable_thinking_hint:
            await self._reply(msg, self._settings.thinking_hint_text)

        retrieval = await asyncio.to_thread(
            self._retriever.retrieve_with_k,
            email_text,
            self._settings.email_short_memory_retrieval_k,
            self._settings.email_long_memory_retrieval_k,
            self._settings.email_chunk_retrieval_k,
        )
        context = _truncate_text(retrieval.context, self._settings.email_context_max_chars)
        prefix = "[建议邮件]"
        if retrieval.source == "db" and retrieval.has_email_case:
            prefix = "[案例回复]"
        try:
            if self._settings.email_split_bilingual:
                english = await asyncio.to_thread(
                    self._llm_client.compose_email_reply_english, email_text, context
                )
                await self._reply(msg, f"{prefix}\n\n[English Reply]\n{english}")
                chinese = await asyncio.to_thread(
                    self._llm_client.translate_email_reply_to_chinese, english
                )
                await self._reply(msg, f"[中文对应]\n{chinese}")
                return

            reply = await asyncio.to_thread(
                self._llm_client.compose_email_reply, email_text, context
            )
        except LLMRequestError as exc:
            await self._reply(msg, exc.user_message)
            return
        await self._reply(msg, f"{prefix}\n\n{reply}")


def _truncate_text(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0:
        return t
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + "\n\n(已截断上下文)"
