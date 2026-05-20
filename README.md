# 电商售后数据分析 Copilot

基于 **Next.js + FastAPI + LangGraph** 的企业数据分析 Agent，支持自然语言查询结构化数据库和非结构化知识库，能自动路由任务、调用工具、生成 SQL、执行校验、引用文档证据、失败反思修复，并提供执行链路、评估指标和运维观测面板。

## 项目亮点

- **LangGraph StateGraph** 编排多角色 Agent 工作流：RouterAgent、SQLAgent、RAGAgent、MemoryAgent、EvaluatorAgent
- **SQL 分支**：schema retrieval → LLM 生成 SQL → 只读校验 → 执行 → 失败反思重试（最多 2 次）
- **RAG 分支**：Chroma 向量检索 + 关键词检索双通路，带文档引用证据
- **Hybrid 分支**：SQL + RAG 并行执行 → 证据融合 → 综合分析
- **Checkpointer**：SqliteSaver 会话持久化，支持断点恢复
- **三层记忆**：recent_turns / conversation_summary / user_profile
- **Trace 可视化**：按 Agent 角色分组的执行链路面板
- **Human-in-the-loop**：高风险 SQL 触发人工审批
- **95 条评估集**：覆盖 SQL/RAG/Hybrid/Clarification/Memory/Ambiguous
- **Docker Compose** 一键启动

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js / React / TypeScript / Tailwind CSS |
| 后端 | FastAPI / Pydantic / LangGraph |
| 数据库 | SQLite（5 表：products, orders, refunds, reviews, tickets） |
| 向量库 | ChromaDB + SiliconFlow BGE-M3 Embedding |
| LLM | SiliconFlow DeepSeek-V3 |
| Agent | LangGraph StateGraph + Checkpointer + Tool Calling |
| 工程化 | Docker Compose / pytest / 结构化日志 / Trace ID |

## 快速开始

### 1. 配置环境变量

```bash
cp apps/api/.env.example apps/api/.env
# 编辑 apps/api/.env，填入 SILICONFLOW_API_KEY
```

### 2. Docker 一键启动（推荐）

```bash
docker-compose up -d
```

前端 http://localhost:3000 | 后端 http://localhost:8000 | API 文档 http://localhost:8000/docs

### 3. 本地开发启动

**后端：**
```bash
cd apps/api
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

**前端：**
```bash
cd apps/web
npm install
npm run dev -- --port 3000
```

### 4. 文档入库

```bash
# 预览 chunk 切分效果
python scripts/ingest_documents.py --dry-run

# 写入 Chroma 向量库
python scripts/ingest_documents.py --reset
```

## 目录结构

```
├── apps/
│   ├── api/                    FastAPI 后端
│   │   ├── app/
│   │   │   ├── api/            HTTP 路由（chat, eval）
│   │   │   ├── core/           配置管理
│   │   │   ├── schemas/        Pydantic 模型
│   │   │   └── services/       Agent / SQL / RAG / Memory / Trace / Eval
│   │   ├── tests/              后端单元测试（35 个）
│   │   └── Dockerfile
│   └── web/                    Next.js 前端
│       ├── app/                页面与全局样式
│       ├── components/         聊天气泡 / Trace 面板 / 类型定义
│       └── Dockerfile
├── data/
│   ├── demo.db                 SQLite 模拟数据库（5 表 ~800 条数据）
│   ├── documents/              10 篇业务知识库 Markdown
│   ├── eval_dataset.jsonl      95 条评估用例
│   └── vector_store/chroma/    Chroma 持久化向量库
├── docs/                       设计文档
├── scripts/                    数据入库 / 冒烟测试 / Demo 脚本
├── docker-compose.yml
└── README.md
```

## Agent 工作流

```
START → classify_intent → route_condition
  ├─ sql    → retrieve_schema → generate_sql → validate_sql
  │         → execute_sql → [retry? → reflect → generate_sql] → format → END
  ├─ rag    → retrieve_docs → format_rag_answer → END
  ├─ hybrid → run_sql_and_rag → merge_evidence → END
  └─ clarification → ask → END
```

## 验收方式

**后端单元测试：**
```bash
cd apps/api
pytest tests/ -v
```

**冒烟测试：**
```bash
python scripts/smoke_test.py
```

**评估运行：**
```bash
curl -X POST http://127.0.0.1:8000/api/eval/run
```

## 评估指标

| 指标 | 说明 |
|---|---|
| task_success_rate | 路由+关键词+工具全部通过率 |
| route_accuracy | 路由判别准确率 |
| keyword_accuracy | 答案关键词命中率 |
| tool_call_accuracy | 工具调用匹配率 |
| sql_execution_success_rate | SQL 执行成功率 |
| citation_hit_rate | 文档引用命中率 |
| avg_latency_ms | 平均延迟 |
| retry_success_rate | SQL 修复重试成功率 |

## 面试讲解要点

- Function Calling 完整链路：Tool Schema → LLM tool_choice → 参数解析 → 本地执行 → result 回传
- LangGraph StateGraph：State、Node、Conditional Edge、Checkpointer
- SQL 安全：正则 + 语法双重只读校验，禁止 DROP/DELETE/UPDATE/INSERT/ALTER
- RAG 设计：chunk strategy、embedding、向量检索、document citation、相邻 chunk 扩展
- Memory 分层：recent_turns（连续追问）、conversation_summary（上下文压缩）、user_profile（偏好记忆）
- Trace 可观测性：每个节点/工具的输入输出、耗时、错误、Agent 角色分组
- Eval 闭环：95 条测试集 → 自动评估 → 指标报告 → bad case → 优化 → 再评估
