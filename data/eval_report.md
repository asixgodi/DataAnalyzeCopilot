# Agent 整链路评估报告

## 当前状态

已将 `data/eval_dataset.jsonl` 重写为中文 UTF-8 版本，覆盖 SQL、RAG、Hybrid、澄清追问、多轮记忆和模糊问题等任务类型。

当前 `data/eval_results.json` 是占位结果文件，表示清理数据集后尚未重新运行整链路评估。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `data/eval_dataset.jsonl` | 整条 Agent 链路测试题库，每行一个 JSON case |
| `data/eval_results.json` | 整链路评估运行后的机器可读结果 |
| `data/eval_report.md` | 给人阅读的评估报告和复盘说明 |
| `scripts/rag_metrics_eval.py` | 单独评估 RAG 检索质量，不等同于整链路评估 |

## 当前测试集覆盖

| 分类 | 数量 | 目标 |
| --- | ---: | --- |
| sql | 8 | 测试自然语言到结构化数据查询 |
| rag | 10 | 测试知识库检索与引用证据 |
| hybrid | 6 | 测试 SQL + RAG 混合分析 |
| clarification | 4 | 测试信息不足时是否追问 |
| memory | 5 | 测试多轮上下文继承 |
| ambiguous | 3 | 测试模糊问题处理 |

## 整链路评估建议指标

- `route_accuracy`：实际路由是否等于期望路由。
- `tool_call_accuracy`：是否调用了期望工具。
- `keyword_accuracy`：答案是否包含期望关键词。
- `sql_execution_success_rate`：SQL 类任务是否成功执行。
- `citation_hit_rate`：RAG/Hybrid 类任务是否返回引用证据。
- `task_success_rate`：综合判断任务是否通过。
- `avg_latency_ms`：平均请求耗时。

## 和 RAG 检索评估的区别

整链路评估关注：

```text
用户问题 -> 路由 -> 工具调用 -> SQL/RAG执行 -> 生成答案 -> trace/metrics
```

RAG 检索评估关注：

```text
用户问题 -> retrieve_docs -> Top-K Citation 是否命中相关文档
```

所以 `data/eval_dataset.jsonl` 是系统级测试集，而 `scripts/rag_metrics_eval.py` 是检索质量测试脚本。

## 下一步

如果要继续完善，可以补一个统一的整链路评估脚本：

```text
scripts/agent_eval.py
```

它读取 `data/eval_dataset.jsonl`，调用 `/api/chat` 或直接调用 `run_agent`，然后生成新的 `data/eval_results.json` 和 `data/eval_report.md`。
