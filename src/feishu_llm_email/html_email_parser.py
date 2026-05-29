import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ParsedHtmlEmail:
    markdown_filename: str
    title: str
    markdown_content: str


class HtmlEmailParser:
    def parse(self, filename: str, html: str, description: str = "") -> ParsedHtmlEmail:
        soup = BeautifulSoup(html, "html.parser")
        subject = self._extract_subject(soup)
        ticket_name = self._build_markdown_name(filename, subject)
        conversations = self._extract_conversations(soup)
        if not conversations:
            fallback = self._normalize_text(soup.get_text("\n"))
            conversations = [{"author": "Unknown", "time": "", "relative": "", "content": fallback}]

        markdown = self._build_markdown(subject, conversations, self._normalize_text(description))
        return ParsedHtmlEmail(
            markdown_filename=ticket_name,
            title=ticket_name,
            markdown_content=markdown,
        )

    def _extract_subject(self, soup: BeautifulSoup) -> str:
        subject_node = soup.select_one('[data-id="caseSubjectText"]') or soup.find("h1")
        text = self._normalize_text(subject_node.get_text("\n") if subject_node else "")
        return text or "Untitled Ticket"

    def _build_markdown_name(self, filename: str, subject: str) -> str:
        base = Path(filename).name
        ticket_match = re.search(r"(#\d+)", base)
        if ticket_match:
            return f"{ticket_match.group(1)}.md"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", subject).strip("_") or "ticket"
        return f"{slug[:80]}.md"

    def _extract_conversations(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items = soup.select('[data-id="ConversationList"]')
        conversations: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            author = self._normalize_text(self._first_text(item, '[data-id="conversationAuthor"]'))
            time_text = self._normalize_text(self._first_text(item, '[data-id="commonTime"]'))
            relative = self._extract_relative_time(item)
            content = self._extract_content(item)
            if not content:
                continue
            key = (author, time_text, content)
            if key in seen:
                continue
            seen.add(key)
            conversations.append(
                {
                    "author": author or "Unknown",
                    "time": time_text,
                    "relative": relative,
                    "content": content,
                }
            )
        return conversations

    def _extract_relative_time(self, node: BeautifulSoup) -> str:
        text = self._normalize_text(node.get_text("\n"))
        match = re.search(r"(\(\s*[^()]+?\s*\))", text)
        return match.group(1) if match else ""

    def _extract_content(self, item: BeautifulSoup) -> str:
        content_node = item.select_one('[data-id="content"]')
        if content_node:
            return self._clean_conversation_body(content_node.get_text("\n"))

        summary_node = item.select_one('[data-id="threadSummary"]')
        summary_text = self._normalize_text(summary_node.get_text("\n") if summary_node else "")
        return self._clean_conversation_body(summary_text)

    def _first_text(self, node: BeautifulSoup, selector: str) -> str:
        selected = node.select_one(selector)
        return selected.get_text("\n") if selected else ""

    def _build_markdown(
        self,
        subject: str,
        conversations: list[dict[str, str]],
        description: str = "",
    ) -> str:
        lines = [f"# {subject}", ""]
        if description:
            lines.extend(["## 邮件说明", "", description, ""])
        for index, convo in enumerate(conversations, start=1):
            lines.append(f"## 会话 {index}")
            lines.append("")
            lines.append(f"- 作者：{convo['author']}")
            if convo["time"]:
                lines.append(f"- 时间：{convo['time']}")
            if convo["relative"]:
                lines.append(f"- 相对时间：{convo['relative']}")
            lines.append("")
            lines.append(convo["content"])
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _normalize_text(text: str) -> str:
        value = text.replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    def _clean_conversation_body(self, text: str) -> str:
        value = self._normalize_text(text)
        if not value:
            return value

        footer_markers = [
            "For technical support on specific products",
            "Seeed Forum",
            "Seeed Discord Community",
            "Official SenseCAP MX Community",
            "Our working hours are",
            "Follow us on",
        ]
        lines = value.splitlines()
        trimmed: list[str] = []
        for line in lines:
            if any(marker in line for marker in footer_markers):
                break
            trimmed.append(line)
        value = self._normalize_text("\n".join(trimmed))

        value = re.sub(r"^Question\s*", "", value)
        value = re.sub(r"\s+[A-Za-z]{3,}\s+\d{1,2}\s+May,\s+\d{1,2}:\d{2}\s+[AP]M\s+", "\n", value)

        if ". " in value and value.count("Hi.") >= 2:
            first, _, second = value.partition("Hi.")
            if second:
                value = "Hi." + second

        duplicate_match = re.match(r"(.+?)(\s+\1)+$", value, flags=re.DOTALL)
        if duplicate_match:
            value = duplicate_match.group(1)

        return self._normalize_text(value)
