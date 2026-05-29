# feishu_llm_email

[中文](#中文说明) | [English](#english)

## 中文说明

### 项目简介

`feishu_llm_email` 是一个面向飞书机器人的知识库问答与邮件辅助回复项目，包含两个核心入口：

- 飞书长连接机器人：接收飞书消息，调用大模型完成问答与邮件回复。
- Web 管理后台：管理知识库文档、任务队列、HTML 邮件导入和 Web 对话。

项目适合以下场景：

- 企业内部知识问答
- 英文/中文邮件回复辅助
- 邮件案例沉淀与复用
- 通过 Markdown、URL、HTML 邮件持续积累知识库

### 主要功能

- 飞书机器人长连接收发消息
- OpenAI 兼容接口接入任意大模型
- Markdown 文档上传入库
- URL 抓取并导入知识库
- HTML 邮件下载、预览、解析为 Markdown
- 短期记忆 / 长期记忆压缩与检索
- 文档编辑、删除、重建短期记忆
- 全量重建长期记忆
- 后台任务队列、进度显示、分页、暂停 / 继续 / 删除
- 按来源、标题关键字、重建次数筛选文档
- 批量删除、批量重建短期记忆
- Web 端独立聊天页
- 三类对话指令：
  - `[邮件]` 生成中英文双语回复邮件
  - `[案例贡献]` 将内容沉淀为可管理文档
  - 普通问答标注来源为数据库或互联网

### 目录结构

```text
feishu_llm_email/
├─ src/feishu_llm_email/
├─ templates/
├─ data/
├─ data_html/
│  └─ downloads/
├─ .env.example
├─ .gitignore
├─ requirements.txt
├─ start.py
├─ start_admin.py
└─ README.md
```

### 环境要求

- Python 3.11
- 已创建并可用的飞书机器人应用
- 可访问的 OpenAI 兼容大模型接口
- macOS / Linux / ARM Linux 均可部署

### 快速开始

#### 1. 安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. 配置环境变量

```bash
cp .env.example .env
```

至少需要填写以下配置：

- `LARK_APP_ID`
- `LARK_APP_SECRET`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

其他可选参数可参考 `.env.example`，其中已包含超时、重试、邮件场景检索和记忆参数。

#### 3. 启动飞书机器人

```bash
python start.py
```

#### 4. 启动管理后台

```bash
python start_admin.py
```

启动后访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

### 使用说明

#### 飞书机器人

- 普通提问：优先检索知识库，命中后标注“来源：数据库”
- 未命中数据库且启用联网搜索：标注“来源：互联网”
- `[邮件]` + 邮件内容：生成中英文双语邮件回复
- `[案例贡献]` + 内容：保存为 Markdown 文档并进入后台任务队列

#### Web 后台

- 上传 Markdown 文档
- 通过 URL 导入网页正文
- 上传 HTML 邮件文件
- 通过 HTML 链接下载原始页面并预览
- 解析并保存邮件内容为 Markdown
- 查看文档详情、切片内容与记忆重建情况
- 管理任务状态和导入进度

### 关键配置说明

- `KNOWLEDGE_DB_PATH`：SQLite 数据库路径
- `ENABLE_MEMORY_PIPELINE`：是否启用短期 / 长期记忆流水线
- `SHORT_MEMORY_RETRIEVAL_K` / `LONG_MEMORY_RETRIEVAL_K` / `CHUNK_RETRIEVAL_K`：普通问答检索参数
- `EMAIL_CONTEXT_MAX_CHARS`：邮件场景上下文截断长度
- `EMAIL_SHORT_MEMORY_RETRIEVAL_K` / `EMAIL_LONG_MEMORY_RETRIEVAL_K` / `EMAIL_CHUNK_RETRIEVAL_K`：邮件场景检索参数
- `EMAIL_SPLIT_BILINGUAL`：是否拆两步生成中英文邮件，降低超时概率
- `ENABLE_THINKING_HINT`：是否先返回“正在思考”提示

### 部署建议

- 生产环境建议使用 `systemd`、`supervisor` 或容器方式托管
- 机器人服务与 Web 后台可分别作为两个进程运行
- 首次启动会自动创建 `data/knowledge.db`
- `data/` 与 `data_html/` 为运行期数据目录，不建议提交真实业务数据
- ARM 设备可直接复用当前工程，依赖均为常见 Python 包，迁移成本较低

### 发布说明

当前目录已经整理为适合单独发布的仓库结构，保留了运行所需的核心内容：

- `src/feishu_llm_email/`：业务源码
- `templates/`：后台页面模板
- `start.py`：机器人启动入口
- `start_admin.py`：后台启动入口
- `requirements.txt`：依赖列表
- `.env.example`：配置模板
- `.gitignore`：运行数据与本地文件忽略规则
- `data/`、`data_html/`：仅保留 `.gitkeep` 占位

发布前建议再确认以下事项：

- `.env` 未被提交
- 数据库、HTML 下载缓存、真实邮件样本未被提交
- 飞书应用凭据已全部改为示例值
- 如需开源，补充 `LICENSE`
- 如需团队协作，补充发布版本号与变更记录

### 推荐发布流程

```bash
git init
git add .
git commit -m "Initial public release"
```

随后将仓库推送到 GitHub。

### 常见问题

#### 机器人无回复

- 检查飞书事件订阅是否开启
- 检查机器人是否在目标会话中具备发言权限
- 检查 `LARK_APP_ID` 和 `LARK_APP_SECRET` 是否正确

#### 模型调用超时

- 缩短输入内容
- 调小邮件场景检索参数
- 开启 `EMAIL_SPLIT_BILINGUAL=true`
- 增大 `LLM_TIMEOUT_SECONDS` 或更换响应更稳定的模型

---

## English

### Overview

`feishu_llm_email` is a Feishu bot project for knowledge-assisted Q&A and email reply generation. It includes two main entry points:

- Feishu long-connection bot for receiving messages and replying with an LLM
- Web admin console for knowledge management, task monitoring, HTML email import, and web chat

Typical use cases:

- Internal knowledge assistant
- English/Chinese email reply drafting
- Email case collection and reuse
- Continuous knowledge ingestion from Markdown, URLs, and HTML emails

### Features

- Feishu bot with long connection
- OpenAI-compatible LLM integration
- Markdown knowledge import
- URL content ingestion
- HTML email download, preview, and Markdown conversion
- Short-term and long-term memory pipeline
- Document edit, delete, and memory rebuild
- Full long-memory rebuild
- Background task queue with progress, pagination, pause, resume, and delete
- Document filtering by source, title keyword, and rebuild count
- Bulk delete and bulk short-memory rebuild
- Dedicated web chat page
- Three message modes:
  - `[邮件]` for bilingual email reply generation
  - `[案例贡献]` for saving a new case into the knowledge base
  - normal Q&A with source labels from database or web

### Project Structure

```text
feishu_llm_email/
├─ src/feishu_llm_email/
├─ templates/
├─ data/
├─ data_html/
│  └─ downloads/
├─ .env.example
├─ .gitignore
├─ requirements.txt
├─ start.py
├─ start_admin.py
└─ README.md
```

### Requirements

- Python 3.11
- A working Feishu bot application
- An accessible OpenAI-compatible LLM API
- Deployable on macOS, Linux, and ARM Linux

### Quick Start

#### 1. Install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. Configure environment variables

```bash
cp .env.example .env
```

At minimum, configure:

- `LARK_APP_ID`
- `LARK_APP_SECRET`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

See `.env.example` for timeout, retry, memory, and email-specific tuning options.

#### 3. Start the Feishu bot

```bash
python start.py
```

#### 4. Start the admin console

```bash
python start_admin.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Usage

#### Feishu bot

- Normal questions: search the knowledge base first and label replies from the database
- If database search misses and web search is enabled: label replies as web-based
- `[邮件]` + email content: generate bilingual email replies
- `[案例贡献]` + content: save the content as a Markdown document and send it to the background queue

#### Web admin

- Upload Markdown documents
- Import content from URLs
- Upload HTML email files
- Download HTML from a link and preview it
- Parse and save email conversations as Markdown
- Review document details, chunks, and memory rebuild status
- Monitor task status and ingestion progress

### Important Settings

- `KNOWLEDGE_DB_PATH`: SQLite database path
- `ENABLE_MEMORY_PIPELINE`: enable short/long memory pipeline
- `SHORT_MEMORY_RETRIEVAL_K`, `LONG_MEMORY_RETRIEVAL_K`, `CHUNK_RETRIEVAL_K`: retrieval settings for normal Q&A
- `EMAIL_CONTEXT_MAX_CHARS`: max context length for email mode
- `EMAIL_SHORT_MEMORY_RETRIEVAL_K`, `EMAIL_LONG_MEMORY_RETRIEVAL_K`, `EMAIL_CHUNK_RETRIEVAL_K`: retrieval settings for email mode
- `EMAIL_SPLIT_BILINGUAL`: generate English and Chinese email replies in two steps for better stability
- `ENABLE_THINKING_HINT`: send a thinking hint before the final reply

### Deployment Notes

- In production, run the bot and admin console as separate processes
- Use `systemd`, `supervisor`, or containers for process management
- The database file `data/knowledge.db` is created automatically on first run
- Keep `data/` and `data_html/` as runtime directories and do not commit real business data
- The project is friendly to ARM devices because it depends on standard Python packages only

### Publishing Notes

This directory has been cleaned up for standalone repository publishing. It includes:

- `src/feishu_llm_email/` for source code
- `templates/` for web UI templates
- `start.py` for the bot entry point
- `start_admin.py` for the admin entry point
- `requirements.txt` for dependencies
- `.env.example` for configuration template
- `.gitignore` for local/runtime exclusions
- `data/` and `data_html/` with `.gitkeep` placeholders only

Before pushing to GitHub, make sure:

- `.env` is not committed
- databases, HTML caches, and real email samples are removed
- Feishu credentials are replaced with sample values
- a `LICENSE` file is added if you want an open-source release
- versioning or release notes are added if needed

### Recommended Release Steps

```bash
git init
git add .
git commit -m "Initial public release"
```

Then push the repository to GitHub.

### Troubleshooting

#### Bot does not reply

- Verify Feishu event subscription is enabled
- Verify the bot has permission to speak in the target chat
- Verify `LARK_APP_ID` and `LARK_APP_SECRET`

#### LLM request times out

- Reduce input length
- Lower email-mode retrieval settings
- Enable `EMAIL_SPLIT_BILINGUAL=true`
- Increase `LLM_TIMEOUT_SECONDS` or switch to a faster, more stable model
