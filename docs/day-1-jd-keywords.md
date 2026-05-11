# 第 1 天：岗位要求关键词整理

目标岗位不是纯算法研究岗，而是更贴近工程落地的方向：

```text
AI Agent 应用开发实习生
大模型应用开发实习生
RAG 工程实习生
LLM Full-stack Intern
AIGC 前端工程实习生
AI 产品工程实习生
```

## JD 高频能力

- Python、FastAPI、REST API、Pydantic、JSON Schema。
- Next.js、React、TypeScript、前端交互和可视化。
- LangGraph、LangChain、Tool Calling、Function Calling。
- RAG：文档切分、Embedding、向量检索、引用证据。
- Text2SQL：schema retrieval、SQL 生成、SQL 校验、执行反馈。
- Agent 流程控制：State、Node、Edge、Conditional Edge、Retry、Fallback。
- 工程化：Git、Docker、环境变量、日志、测试、API 文档。
- 可观测性：trace_id、run_id、工具输入输出、节点耗时、错误定位。
- 可评估性：eval dataset、任务完成率、工具调用准确率、bad case 分析。

## 本项目对应关系

| JD 能力 | 项目实现 |
| --- | --- |
| 前端产品化 | Next.js 聊天界面、执行链路面板、指标 dashboard |
| 后端服务化 | FastAPI 提供 `/api/chat`、`/health`、trace/eval 接口 |
| Agent 编排 | LangGraph StateGraph + Conditional Edge |
| 工具调用 | SQL 工具、RAG 检索工具、业务规则工具 |
| 数据查询 | SQLite demo database + Text2SQL |
| 知识检索 | Markdown 业务文档 + Chroma/FAISS |
| 可靠性 | SQL 只读校验、失败反思修复、重试上限 |
| 可观测性 | run_id、trace_id、node log、tool log |
| 可评估性 | JSONL 测试集、自动评估脚本、bad case 报告 |
