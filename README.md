# 电商售后数据分析 Copilot

这是一个面向面试展示的全栈 Agent MVP。项目不是泛聊天机器人，而是一个能处理电商售后业务问题的分析助手：用户用自然语言提问，系统自动路由到 SQL、RAG 或混合分析链路，并返回答案、SQL、文档证据、执行链路、记忆状态和基础评估指标。

## 项目能做什么

- 自然语言查询结构化售后数据库，例如“4月服装类商品退款率是多少？”
- 检索非结构化业务知识库，例如“退款率指标口径是什么？”
- 对需要数据和文档证据的问题走 Hybrid 链路，例如“4月服装类商品退款率为什么升高？”
- 展示 Router、SQLAgent、RAGAgent、MemoryAgent、EvaluatorAgent 的执行过程。
- 提供 smoke test 和 eval endpoint，用于验证路由、回答和基本回归指标。

## 技术选型

- 前端：Next.js、React、TypeScript
- 后端：FastAPI、Pydantic
- 数据库：SQLite 模拟电商售后结构化数据
- 知识库：Markdown 文档 + 本地检索
- Agent 能力：任务路由、SQL 工具、RAG 工具、会话记忆、Trace、Eval

当前版本优先完成可运行闭环。真实企业落地时，可以把本地规则路由替换为 LangGraph，把 Markdown 检索替换为 ChromaDB/FAISS + Embedding，把 SQLite 替换为 MySQL/PostgreSQL。

## 目录结构

```text
apps/
  api/                 FastAPI 后端
    app/
      api/             HTTP 路由
      schemas/         请求和响应模型
      services/        Agent、SQL、RAG、Memory、Trace、Eval
  web/                 Next.js 前端控制台
data/
  documents/           模拟企业知识库 Markdown
  demo.db              首次运行后自动生成的 SQLite 数据库
docs/
  task-complete-mvp.md 工程化需求对齐文档
scripts/
  smoke_test.py        端到端冒烟测试
```

## 后端启动

```powershell
cd D:\yjs\front\agent\apps\api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

访问：

- Health check: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

## 前端启动

```powershell
cd D:\yjs\front\agent
npm run dev:web
```

访问：

- Web: http://localhost:3000

如后端端口不是 8000，可以在 `apps/web/.env.local` 中配置：

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## 验收方式

后端冒烟测试：

```powershell
cd D:\yjs\front\agent
.\apps\api\.venv\Scripts\python.exe -B scripts\smoke_test.py
```

前端构建：

```powershell
cd D:\yjs\front\agent
npm run build:web
```

接口评估：

```powershell
curl -X POST http://127.0.0.1:8000/api/eval/run
```

## Chroma 文档入库

真实 RAG 入库前，先复制 `apps/api/.env.example` 为 `apps/api/.env`，并填入 `SILICONFLOW_API_KEY`。

先查看 chunk 切分效果，不调用模型：

```powershell
cd D:\yjs\front\agent
.\apps\api\.venv\Scripts\python.exe scripts\ingest_documents.py --dry-run
```

确认切分效果后，写入 Chroma：

```powershell
.\apps\api\.venv\Scripts\python.exe scripts\ingest_documents.py --reset
```

切分策略说明见：

```text
docs/rag-chunking-and-chroma.md
```

## 已知限制

- 当前是本地确定性 MVP，没有调用真实 LLM。
- RAG 使用本地轻量检索，尚未接入 Embedding、向量数据库和 RRF。
- 记忆系统保存在进程内，服务重启后会丢失。
- 数据是模拟电商售后数据，适合展示工程闭环和面试讲解，不代表真实企业数据。
