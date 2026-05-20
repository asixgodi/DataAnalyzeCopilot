# 系统架构

## 整体架构

```
User → Next.js Web App → FastAPI Agent API → LangGraph StateGraph
                                                    │
                          ┌─────────────────────────┼─────────────────────────┐
                          ▼                         ▼                         ▼
                    RouterAgent               SQLAgent                  RAGAgent
                    (classify_intent)    (generate/validate/       (retrieve_docs/
                          │              execute/reflect)          format_answer)
                          │                         │                         │
                          └─────────────────────────┼─────────────────────────┘
                                                    ▼
                                            MemoryAgent + EvaluatorAgent
                                                    │
                                                    ▼
                                            Trace Logger + Eval Harness
```

## LangGraph 工作流

```
START
  │
  ▼
classify_intent ──(conditional edge)──┬── sql ──────────────────────────────────┐
                                      │    retrieve_schema → generate_sql       │
                                      │    → validate_sql → execute_sql         │
                                      │    → [error? → reflect → generate_sql]  │
                                      │    → format_sql_answer                  │
                                      │                                         │
                                      ├── rag ──────────────────────────────────┤
                                      │    retrieve_docs → format_rag_answer    │
                                      │                                         │
                                      ├── hybrid ───────────────────────────────┤
                                      │    run_sql_and_rag → merge_evidence     │
                                      │                                         │
                                      └── clarification ────────────────────────┘
                                                         │
                                                         ▼
                                                  generate_final
                                                         │
                                                         ▼
                                                        END
```

## 核心组件

### RouterAgent（classify_intent + route_condition）
- 基于关键词规则的路由判定
- 4 种路由：sql / rag / hybrid / clarification
- 输出：route + reason + confidence

### SQLAgent（sql_retrieve_schema → sql_generate → sql_validate → sql_execute → sql_reflect）
- Schema 自动获取（PRAGMA table_info）
- SQL 生成：模板匹配优先 + LLM 补充（DeepSeek-V3）
- 只读校验：正则 + 语法双重检查
- 执行失败：自动反思重试（最多 2 次）
- 预编译正则阻止 DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE

### RAGAgent（rag_retrieve → format_rag_answer）
- ChromaDB 向量检索（BGE-M3 Embedding）
- 回退关键词检索（Query Rewrite + Multi Query 扩展）
- 文档引用带 doc_id、chunk_id、score、snippet
- 相邻 chunk 扩展（通过 chunk_index 关联）

### MemoryAgent（三层记忆）
- recent_turns：最近 6 轮完整对话
- conversation_summary：历史压缩摘要
- user_profile：用户角色和关注偏好
- 追问指代消解：继承上一轮时间范围和类目

### EvaluatorAgent（confidence_check + final_answer）
- 答案完整性和一致性检查
- 高风险操作触发 HITL 审批

## 数据层

### 结构化数据（SQLite）
```
products ──< orders ──< refunds
   │           │
   ├──< reviews
   └──< tickets
```

### 非结构化数据（ChromaDB）
10 篇 Markdown 文档 → chunking → embedding → Chroma 向量库

## 前端组件

### 会话管理
- localStorage 持久化会话列表
- 新建 / 切换 / 删除会话
- 会话切换时恢复聊天历史

### 聊天区
- 用户 / Assistant 对话气泡
- SQL 结果可折叠表格
- 文档引用卡片
- HITL 审批卡片

### Trace 面板
- 按 Agent 角色分组（Router/SQL/RAG/Memory/Evaluator）
- 时间线展示 + 展开 metadata
- 每条步骤显示状态和耗时

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 健康检查 |
| POST | /api/chat | 主对话端点 |
| POST | /api/chat/approve | HITL 审批 |
| POST | /api/eval/run | 触发评估 |

## 工程化

- Docker Compose 一键启动（api + web）
- pytest 单元测试（35 个，覆盖 SQL 校验 / 路由 / 记忆 / 评估）
- 结构化 Trace 日志
- 95 条 Eval 用例 × 9 项指标
