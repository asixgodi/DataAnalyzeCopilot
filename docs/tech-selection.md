# 技术选型说明

## 前端：Next.js + React + TypeScript

选择原因：

- 与已有前端实习经历匹配，能体现已有优势。
- 适合构建可演示的 Agent 产品界面，而不是只做命令行 demo。
- 后续可以展示聊天区、执行步骤时间线、SQL 面板、文档引用和评估 dashboard。

面试说法：

```text
我选择 Next.js + React，是因为这个项目需要把 Agent 的执行过程产品化展示出来。相比只写后端脚本，前端可以展示工具调用、SQL、RAG 引用和评估指标，更容易说明我能把 Agent 做成真实可用的应用。
```

## 后端：FastAPI + Pydantic

选择原因：

- Python 生态适合接 LangGraph、RAG、向量库和评估脚本。
- FastAPI 自带 OpenAPI 文档，适合服务化。
- Pydantic 适合定义 Agent 输入输出、工具参数和统一错误格式。

面试说法：

```text
我用 FastAPI 做 Agent 服务层，因为 Agent 逻辑主要在 Python 生态里，FastAPI 能把 LangGraph workflow、SQL tools 和 RAG pipeline 暴露成稳定 API，同时方便前端联调和后续部署。
```

## Agent 编排：LangGraph

选择原因：

- 项目包含 SQL、RAG、Hybrid、追问、失败修复等多分支流程。
- StateGraph 能清晰表达状态传递。
- Conditional Edge 适合控制任务路由。
- Checkpointer 可以支持会话恢复。

面试说法：

```text
我没有只用普通 chain，而是选择 LangGraph，是因为这个项目不是单轮问答，而是一个有状态、有分支、有失败恢复的 Agent workflow。LangGraph 可以把 classify、route、SQL、RAG、reflection、final answer 拆成清晰节点，方便调试和扩展。
```

## 数据库：SQLite 优先，PostgreSQL 可替换

选择原因：

- SQLite 轻量，适合 demo 阶段和面试官本地运行。
- SQLAlchemy 可以让后续迁移到 PostgreSQL。
- 项目重点是 Text2SQL 工具设计和只读执行校验。

面试说法：

```text
我 demo 阶段使用 SQLite，是为了让项目易启动、易复现。真实企业场景可以换成 PostgreSQL 或内部数仓，Agent 层只需要替换连接配置和 schema 获取工具。
```

## 向量库：Chroma 或 FAISS

选择原因：

- 本地开发简单，不依赖复杂云服务。
- 能满足文档检索、metadata、score 和 citation 展示。
- 后续可以替换成 Milvus、pgvector 或企业内部检索服务。

面试说法：

```text
RAG 这部分我先选 Chroma/FAISS，是因为它们适合本地开发和演示。项目关注的是文档切分、检索、引用证据和评估链路，而不是绑定某一个向量数据库。
```

## 评估集：JSONL

选择原因：

- 一行一个 case，适合批量跑 eval。
- 易于记录 `question`、`expected_route`、`expected_tools`、`expected_answer_keywords`。
- 方便生成 Markdown 和 JSON 报告。
