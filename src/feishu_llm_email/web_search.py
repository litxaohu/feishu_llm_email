from dataclasses import dataclass
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


class DuckDuckGoSearch:
    def __init__(self, timeout_seconds: int = 12) -> None:
        self._timeout = timeout_seconds

    def search(self, query: str, max_results: int) -> list[WebResult]:
        q = (query or "").strip()
        if not q:
            return []
        url = f"https://duckduckgo.com/html/?q={quote_plus(q)}"
        resp = requests.get(
            url,
            timeout=self._timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[WebResult] = []
        for item in soup.select(".result"):
            a = item.select_one("a.result__a")
            if not a:
                continue
            title = a.get_text(" ", strip=True)
            href = a.get("href") or ""
            snippet_el = item.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if href and title:
                results.append(WebResult(title=title, url=href, snippet=snippet))
            if len(results) >= max_results:
                break
        return results
