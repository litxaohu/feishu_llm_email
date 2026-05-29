import time
from typing import Any

import requests

from .config import Settings


class LLMRequestError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def ask(self, question: str, context: str = "") -> str:
        user_prompt = question
        if context.strip():
            user_prompt = (
                "请基于以下资料优先回答问题；若资料未覆盖，请明确说明并给出可执行建议。\n\n"
                f"资料如下：\n{context}\n\n"
                f"用户问题：{question}"
            )
        messages = [
            {"role": "system", "content": self._settings.llm_system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._chat(messages, temperature=0.3)

    def summarize_short_memory(self, chunk_text: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是知识提炼助手。请把输入内容提炼为50-120字的短期记忆，"
                    "保留关键事实、术语、结论，不要空话。"
                ),
            },
            {"role": "user", "content": chunk_text},
        ]
        return self._chat(messages, temperature=0.2)

    def summarize_long_memory(self, short_memory_block: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是长期记忆归纳助手。请把多条短期记忆聚合为长期记忆，"
                    "输出要点化内容（3-8条），强调稳定结论与约束。"
                ),
            },
            {"role": "user", "content": short_memory_block},
        ]
        return self._chat(messages, temperature=0.2)

    def compose_email_reply(
        self,
        original_email: str,
        context: str,
        signature_name: str = "XXX",
    ) -> str:
        signature = (
            "Best Regards!\n"
            f"{signature_name}\n"
            "Seeed Technical Support Team\n"
            "------------------------------"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Seeed Technical Support Team 的邮件回复助手。"
                    "请基于给定资料与用户邮件，生成一封专业、简洁、可直接发送的回复邮件。"
                    "必须输出英文回复邮件，并提供对应中文版本。"
                    "必须使用固定签名结尾，签名内容不可更改。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"资料（若无可用资料可忽略）：\n{context}\n\n"
                    f"用户邮件原文：\n{original_email}\n\n"
                    "请严格按以下格式输出：\n"
                    "[English Reply]\n"
                    "<英文正文>\n"
                    f"{signature}\n\n"
                    "[中文对应]\n"
                    "<中文正文>\n"
                    f"{signature}\n"
                ),
            },
        ]
        text = self._chat(messages, temperature=0.2).strip()
        if "Seeed Technical Support Team" not in text:
            text = text + "\n\n" + signature
        return text

    def compose_email_reply_english(
        self,
        original_email: str,
        context: str,
        signature_name: str = "XXX",
    ) -> str:
        signature = (
            "Best Regards!\n"
            f"{signature_name}\n"
            "Seeed Technical Support Team\n"
            "------------------------------"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Seeed Technical Support Team 的邮件回复助手。"
                    "请基于给定资料与用户邮件，生成一封专业、简洁、可直接发送的英文回复邮件。"
                    "必须使用固定签名结尾，签名内容不可更改。"
                    "不要输出中文。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"资料（若无可用资料可忽略）：\n{context}\n\n"
                    f"用户邮件原文：\n{original_email}\n\n"
                    "请输出英文正文，并以固定签名结尾：\n"
                    f"{signature}\n"
                ),
            },
        ]
        text = self._chat(messages, temperature=0.2).strip()
        if "Seeed Technical Support Team" not in text:
            text = text + "\n\n" + signature
        return text

    def translate_email_reply_to_chinese(
        self,
        english_reply: str,
        signature_name: str = "XXX",
    ) -> str:
        signature = (
            "Best Regards!\n"
            f"{signature_name}\n"
            "Seeed Technical Support Team\n"
            "------------------------------"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是邮件翻译助手。请把英文邮件翻译成中文，保持专业语气与含义一致。"
                    "必须以固定签名结尾，签名内容不可更改。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"英文邮件如下：\n{english_reply}\n\n"
                    "请输出中文版本邮件正文，并以固定签名结尾：\n"
                    f"{signature}\n"
                ),
            },
        ]
        text = self._chat(messages, temperature=0.2).strip()
        if "Seeed Technical Support Team" not in text:
            text = text + "\n\n" + signature
        return text

    def _chat(self, messages: list[dict[str, str]], temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if self._settings.llm_max_tokens > 0:
            payload["max_tokens"] = self._settings.llm_max_tokens
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._settings.llm_base_url}/chat/completions"
        attempts = max(1, self._settings.llm_max_retries + 1)
        last_exc: Exception | None = None

        for idx in range(attempts):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._settings.llm_timeout_seconds,
                )
                if response.status_code in (401, 403):
                    raise LLMRequestError("模型鉴权失败，请检查 API Key 或权限配置。")
                if response.status_code == 429:
                    raise LLMRequestError("模型接口限流，请稍后再试。")
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    return "模型暂时未返回内容，请稍后重试。"

                message = choices[0].get("message") or {}
                content = (message.get("content") or "").strip()
                return content or "模型返回为空，请稍后重试。"
            except LLMRequestError:
                raise
            except requests.exceptions.ReadTimeout as exc:
                last_exc = exc
                if idx < attempts - 1:
                    time.sleep(self._settings.llm_retry_backoff_seconds * (idx + 1))
                    continue
                raise LLMRequestError("模型响应超时，请稍后重试。") from exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if idx < attempts - 1:
                    time.sleep(self._settings.llm_retry_backoff_seconds * (idx + 1))
                    continue
                raise LLMRequestError("模型网络请求失败，请稍后重试。") from exc
            except Exception as exc:
                raise LLMRequestError("模型返回异常，请稍后重试。") from exc

        raise LLMRequestError("模型调用失败，请稍后重试。") from last_exc
