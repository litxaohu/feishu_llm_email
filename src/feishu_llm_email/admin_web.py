import math
from pathlib import Path
from urllib.parse import quote

import requests

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import load_settings
from .knowledge_service import KnowledgeService
from .knowledge_store import KnowledgeStore
from .llm_client import LLMClient
from .memory_pipeline import MemoryPipeline
from .retriever import KnowledgeRetriever
from .task_dispatcher import TaskDispatcher, TaskType
from .web_search import DuckDuckGoSearch


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
HTML_DIR = BASE_DIR / "data_html"
HTML_DOWNLOAD_DIR = HTML_DIR / "downloads"
TEMPLATES_DIR = BASE_DIR / "templates"

settings = load_settings()
store = KnowledgeStore(BASE_DIR / settings.knowledge_db_path)
llm_client = LLMClient(settings)
memory_pipeline = MemoryPipeline(store, llm_client, settings)
service = KnowledgeService(store, memory_pipeline=memory_pipeline)
dispatcher = TaskDispatcher(store, service, memory_pipeline)
retriever = KnowledgeRetriever(store, settings)
web_search = DuckDuckGoSearch()

app = FastAPI(title="Feishu LLM XiaoHu Admin")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render_index(
    request: Request,
    message: str = "",
    docs_page: int = 1,
    tasks_page: int = 1,
    source_type: str = "",
    rebuild_count: str = "",
    title_keyword: str = "",
) -> HTMLResponse:
    rebuild_value = int(rebuild_count) if rebuild_count.isdigit() else None
    docs, docs_total = store.list_documents(
        page=docs_page,
        page_size=50,
        source_type=source_type,
        rebuild_count=rebuild_value,
        title_keyword=title_keyword,
    )
    tasks, tasks_total = store.list_tasks(page=tasks_page, page_size=10)
    options = store.get_document_filter_options()
    source_type_labels = {
        "url": "URL",
        "markdown": "Markdown",
        "contribution": "AI对话收录",
    }
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "documents": docs,
            "tasks": tasks,
            "message": message,
            "docs_page": docs_page,
            "docs_total_pages": max(1, math.ceil(docs_total / 50)),
            "tasks_page": tasks_page,
            "tasks_total_pages": max(1, math.ceil(tasks_total / 10)),
            "selected_source_type": source_type,
            "selected_rebuild_count": rebuild_count,
            "selected_title_keyword": title_keyword,
            "source_types": options["source_types"],
            "rebuild_counts": options["rebuild_counts"],
            "source_type_labels": source_type_labels,
        },
    )


def _render_chat_page(
    request: Request,
    message: str = "",
    chat_input: str = "",
    chat_output: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "message": message,
            "chat_input": chat_input,
            "chat_output": chat_output,
        },
    )


def _render_html_import_page(
    request: Request,
    stored_name: str,
    source_url: str = "",
    description: str = "",
    message: str = "",
) -> HTMLResponse:
    preview_url = f"/html-preview?stored_name={quote(stored_name)}"
    return templates.TemplateResponse(
        request=request,
        name="html_import.html",
        context={
            "stored_name": stored_name,
            "source_url": source_url,
            "description": description,
            "message": message,
            "preview_url": preview_url,
        },
    )


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    message: str = Query(default=""),
    docs_page: int = Query(default=1),
    tasks_page: int = Query(default=1),
    source_type: str = Query(default=""),
    rebuild_count: str = Query(default=""),
    title_keyword: str = Query(default=""),
) -> HTMLResponse:
    return _render_index(
        request=request,
        message=message,
        docs_page=docs_page,
        tasks_page=tasks_page,
        source_type=source_type,
        rebuild_count=rebuild_count,
        title_keyword=title_keyword,
    )


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, message: str = Query(default="")) -> HTMLResponse:
    return _render_chat_page(request=request, message=message)


@app.get("/html-import", response_class=HTMLResponse)
def html_import_page(
    request: Request,
    stored_name: str = Query(...),
    source_url: str = Query(default=""),
    description: str = Query(default=""),
    message: str = Query(default=""),
) -> HTMLResponse:
    stored_path = _resolve_downloaded_html(stored_name)
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail="下载的 HTML 文件不存在")
    return _render_html_import_page(
        request=request,
        stored_name=stored_name,
        source_url=source_url,
        description=description,
        message=message,
    )


@app.get("/html-preview", response_class=HTMLResponse)
def html_preview(stored_name: str = Query(...)) -> HTMLResponse:
    stored_path = _resolve_downloaded_html(stored_name)
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail="下载的 HTML 文件不存在")
    return HTMLResponse(content=stored_path.read_text(encoding="utf-8", errors="ignore"))


@app.post("/upload-md")
async def upload_markdown(file: UploadFile = File(...)) -> RedirectResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    content = (await file.read()).decode("utf-8", errors="ignore")
    task_id = dispatcher.enqueue(
        TaskType.INGEST_MARKDOWN,
        payload={"filename": filename, "content": content},
    )
    return RedirectResponse(url=f"/?message=任务已提交，任务ID={task_id}", status_code=303)


@app.post("/upload-html")
async def upload_html(
    file: UploadFile = File(...),
    description: str = Form(default=""),
) -> RedirectResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".html"):
        raise HTTPException(status_code=400, detail="仅支持 .html 文件")
    content = (await file.read()).decode("utf-8", errors="ignore")
    task_id = dispatcher.enqueue(
        TaskType.INGEST_HTML,
        payload={
            "filename": filename,
            "content": content,
            "description": description.strip(),
            "base_dir": str(BASE_DIR),
        },
    )
    return RedirectResponse(
        url=f"/?message=HTML解析任务已提交，任务ID={task_id}。文档会先保存，需手动点击重建后才生成记忆。",
        status_code=303,
    )


@app.post("/download-html")
def download_html(
    html_url: str = Form(...),
    description: str = Form(default=""),
) -> RedirectResponse:
    url = html_url.strip()
    if not url:
        return RedirectResponse(url="/?message=请输入 HTML 邮件链接", status_code=303)
    if not url.startswith(("http://", "https://")):
        return RedirectResponse(url="/?message=链接必须以 http:// 或 https:// 开头", status_code=303)

    HTML_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/?message=HTML 下载失败：{exc}", status_code=303)

    filename = _build_download_filename(url)
    stored_path = HTML_DOWNLOAD_DIR / filename
    stored_path.write_text(response.text, encoding="utf-8")
    return RedirectResponse(
        url=(
            f"/html-import?stored_name={quote(filename)}"
            f"&source_url={quote(url)}&description={quote(description.strip())}"
            "&message=HTML 已下载，请先预览再确认解析"
        ),
        status_code=303,
    )


@app.post("/confirm-html")
def confirm_html_import(
    stored_name: str = Form(...),
    description: str = Form(default=""),
    source_url: str = Form(default=""),
) -> RedirectResponse:
    stored_path = _resolve_downloaded_html(stored_name)
    if not stored_path.exists():
        return RedirectResponse(url="/?message=下载的 HTML 文件不存在", status_code=303)
    content = stored_path.read_text(encoding="utf-8", errors="ignore")
    task_id = dispatcher.enqueue(
        TaskType.INGEST_HTML,
        payload={
            "filename": stored_path.name,
            "content": content,
            "description": description.strip(),
            "base_dir": str(BASE_DIR),
        },
    )
    return RedirectResponse(
        url=f"/?message=HTML 解析任务已提交，任务ID={task_id}。文档会先保存，需手动点击重建后才生成记忆。",
        status_code=303,
    )


@app.post("/add-url")
def add_url(url: str = Form(...)) -> RedirectResponse:
    try:
        task_id = dispatcher.enqueue(TaskType.INGEST_URL, payload={"url": url.strip()})
        return RedirectResponse(url=f"/?message=任务已提交，任务ID={task_id}", status_code=303)
    except Exception as exc:
        return RedirectResponse(
            url=f"/?message=URL+入库失败:+{str(exc)}",
            status_code=303,
        )


@app.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(
    document_id: int, request: Request, message: str = Query(default="")
) -> HTMLResponse:
    doc = store.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return templates.TemplateResponse(
        request=request,
        name="document_detail.html",
        context={"doc": doc, "message": message},
    )


@app.post("/documents/bulk")
def bulk_manage_documents(
    action: str = Form(...),
    selected_document_ids: list[int] = Form(default=[]),
    source_type: str = Form(default=""),
    rebuild_count: str = Form(default=""),
    title_keyword: str = Form(default=""),
    rebuild_long_memory: str = Form(default="false"),
) -> RedirectResponse:
    if not selected_document_ids:
        return RedirectResponse(url="/?message=请先选择文档", status_code=303)
    created = 0
    for document_id in selected_document_ids:
        if action == "bulk_delete":
            dispatcher.enqueue(
                TaskType.DELETE_DOCUMENT,
                payload={"rebuild_long_memory": rebuild_long_memory == "true"},
                document_id=document_id,
            )
            created += 1
        elif action == "bulk_reindex":
            dispatcher.enqueue(TaskType.REINDEX_DOCUMENT, payload={}, document_id=document_id)
            created += 1
    query = (
        f"/?message=已提交{created}个任务"
        f"&source_type={source_type}&rebuild_count={rebuild_count}&title_keyword={title_keyword}"
    )
    return RedirectResponse(url=query, status_code=303)


@app.post("/documents/{document_id}/reindex")
def reindex_document(document_id: int) -> RedirectResponse:
    task_id = dispatcher.enqueue(TaskType.REINDEX_DOCUMENT, payload={}, document_id=document_id)
    return RedirectResponse(url=f"/?message=重建任务已提交，任务ID={task_id}", status_code=303)


@app.post("/documents/{document_id}/delete")
def delete_document(
    document_id: int,
    rebuild_long_memory: str = Form(default="false"),
) -> RedirectResponse:
    task_id = dispatcher.enqueue(
        TaskType.DELETE_DOCUMENT,
        payload={"rebuild_long_memory": rebuild_long_memory == "true"},
        document_id=document_id,
    )
    suffix = "并将重建长期记忆" if rebuild_long_memory == "true" else "不重建长期记忆"
    return RedirectResponse(url=f"/?message=删除任务已提交，任务ID={task_id}，{suffix}", status_code=303)


@app.post("/documents/{document_id}/update")
def update_document(
    document_id: int,
    title: str = Form(...),
    source_ref: str = Form(...),
    content: str = Form(...),
) -> RedirectResponse:
    task_id = dispatcher.enqueue(
        TaskType.UPDATE_DOCUMENT,
        payload={"title": title, "source_ref": source_ref, "content": content},
        document_id=document_id,
    )
    return RedirectResponse(
        url=f"/documents/{document_id}?message=更新任务已提交，任务ID={task_id}",
        status_code=303,
    )


@app.post("/memories/rebuild-long")
def rebuild_long_memories() -> RedirectResponse:
    task_id = dispatcher.enqueue(TaskType.REBUILD_LONG_MEMORY, payload={})
    return RedirectResponse(url=f"/?message=长期记忆重建任务已提交，任务ID={task_id}", status_code=303)


@app.post("/tasks/{task_id}/pause")
def pause_task(task_id: int) -> RedirectResponse:
    try:
        dispatcher.pause_task(task_id)
        return RedirectResponse(url=f"/?message=任务 {task_id} 已暂停", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/?message=暂停任务失败：{exc}", status_code=303)


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: int) -> RedirectResponse:
    try:
        dispatcher.resume_task(task_id)
        return RedirectResponse(url=f"/?message=任务 {task_id} 已继续", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/?message=继续任务失败：{exc}", status_code=303)


@app.post("/tasks/{task_id}/delete")
def delete_task(task_id: int) -> RedirectResponse:
    try:
        dispatcher.delete_task(task_id)
        return RedirectResponse(url=f"/?message=任务 {task_id} 已删除", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/?message=删除任务失败：{exc}", status_code=303)


@app.post("/chat", response_class=HTMLResponse)
def chat(
    request: Request,
    chat_input: str = Form(...),
) -> HTMLResponse:
    try:
        chat_output = _process_chat_message(chat_input.strip())
    except Exception as exc:  # noqa: BLE001
        chat_output = f"处理失败：{type(exc).__name__}: {exc}"
    return _render_chat_page(
        request=request,
        chat_input=chat_input,
        chat_output=chat_output,
    )


def _process_chat_message(message: str) -> str:
    if not message:
        return "请输入问题后再发送。"

    if message.startswith("[案例贡献]") or message.startswith("【案例贡献】"):
        content = message.replace("[案例贡献]", "", 1).replace("【案例贡献】", "", 1).strip()
        if not content:
            return "请在 [案例贡献] 后输入要收录的内容。"
        from datetime import datetime

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = f"case_contribution_{now}.md"
        markdown = f"# 案例贡献 {now}\n\n## 原始内容\n\n{content}\n"
        task_id = dispatcher.enqueue(
            TaskType.INGEST_CONTRIBUTION,
            payload={"title": title, "source_ref": title, "content": markdown, "base_dir": str(BASE_DIR)},
        )
        return f"已收到案例贡献，后台处理中，任务ID={task_id}。"

    if message.startswith("[邮件]") or message.startswith("【邮件】"):
        email_text = message.replace("[邮件]", "", 1).replace("【邮件】", "", 1).strip()
        if not email_text:
            return "请在 [邮件] 后粘贴要回复的邮件原文。"
        retrieval = retriever.retrieve_with_k(
            email_text,
            settings.email_short_memory_retrieval_k,
            settings.email_long_memory_retrieval_k,
            settings.email_chunk_retrieval_k,
        )
        context = _truncate_text(retrieval.context, settings.email_context_max_chars)
        prefix = "[案例回复]" if retrieval.source == "db" and retrieval.has_email_case else "[建议邮件]"
        if settings.email_split_bilingual:
            english = llm_client.compose_email_reply_english(email_text, context)
            chinese = llm_client.translate_email_reply_to_chinese(english)
            return f"{prefix}\n\n[English Reply]\n{english}\n\n[中文对应]\n{chinese}"
        reply = llm_client.compose_email_reply(email_text, context)
        return f"{prefix}\n\n{reply}"

    retrieval = retriever.retrieve(message)
    if retrieval.source == "db":
        answer = llm_client.ask(message, retrieval.context)
        return f"【来源：数据库】\n\n{answer}"
    if settings.enable_web_search:
        results = web_search.search(message, settings.web_search_max_results)
        if results:
            web_context = "【互联网检索结果】\n" + "\n".join(
                f"- {item.title}\n  {item.snippet}\n  {item.url}" for item in results
            )
            answer = llm_client.ask(message, web_context)
            return f"【来源：互联网】\n\n{answer}"
    answer = llm_client.ask(message)
    return f"【来源：模型】\n\n{answer}"


def _truncate_text(text: str, max_chars: int) -> str:
    value = (text or "").strip()
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n\n(已截断上下文)"


def _build_download_filename(url: str) -> str:
    from datetime import datetime
    from urllib.parse import urlparse
    import re

    parsed = urlparse(url)
    base_name = Path(parsed.path).name or parsed.netloc or "downloaded_html"
    stem = Path(base_name).stem or "downloaded_html"
    safe_stem = re.sub(r"[^A-Za-z0-9._#-]+", "_", stem).strip("_") or "downloaded_html"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{safe_stem}.html"


def _resolve_downloaded_html(stored_name: str) -> Path:
    candidate = (HTML_DOWNLOAD_DIR / stored_name).resolve()
    base = HTML_DOWNLOAD_DIR.resolve()
    if base not in candidate.parents and candidate != base:
        raise HTTPException(status_code=400, detail="非法的 HTML 路径")
    return candidate


@app.on_event("startup")
def on_startup() -> None:
    dispatcher.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    dispatcher.stop()
