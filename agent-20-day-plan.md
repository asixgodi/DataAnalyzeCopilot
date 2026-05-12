# Agent 开发实习 20 天冲刺计划

## 项目先读说明

这个项目不是做一个“什么都能聊”的聊天机器人，而是做一个更接近企业真实需求的业务分析助手。用户不用会 SQL，也不用自己翻业务文档，直接用自然语言提问，系统会自动判断该查数据库、查知识库，还是两者都查，然后把数据结果、文档证据和分析结论合并返回。

推荐把文档里的“企业数据分析 Copilot”进一步收敛成一个更具体的场景：

```text
电商售后数据分析 Copilot
```

这个场景适合实习项目，因为数据好模拟、业务逻辑容易理解，也能同时覆盖 Text2SQL、RAG、Agent 路由、工具调用、可观测性和评估。

一个典型问题可以是：

```text
4 月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。
```

系统应该完成的流程是：

```text
用户自然语言问题
→ 判断这是 SQL + RAG 混合问题
→ 查询订单、商品、退款、评价、客服工单等结构化数据
→ 检索退款政策、售后 SOP、指标口径等非结构化文档
→ 生成 SQL 并只读执行
→ 引用相关文档片段作为证据
→ 合并数据结果和政策依据
→ 输出原因分析、SQL、文档引用、执行链路和耗时指标
```

## 数据和知识库从哪里来

这个项目不需要真实企业数据，也不应该使用真实企业内部数据。实习项目使用模拟业务数据是合理的，关键是要把数据结构、业务规则和评估方式设计得像真实场景。

结构化数据库可以自己构造，例如：

```text
users 用户表
products 商品表
orders 订单表
refunds 退款表
reviews 评价表
tickets 客服工单表
```

非结构化知识库就是 RAG 的知识来源，可以自己写成 Markdown 文档，例如：

```text
退款政策.md
商品分类说明.md
售后处理 SOP.md
会员等级规则.md
物流时效说明.md
退款率指标口径.md
客服工单分类标准.md
```

面试时可以这样解释数据来源：

```text
本项目使用模拟电商售后业务数据，重点验证 Agent 在结构化数据查询、非结构化知识检索、工具调用、执行链路追踪和自动评估上的工程能力。真实落地时，只需要替换数据库连接、业务文档和权限系统即可。
```

## 面试时的技术选型说法

可以用下面这套说法回答“为什么这么选技术栈”：

- 前端选择 Next.js + React：因为我有前端实习经验，能把 Agent 能力做成可交互、可演示、可部署的产品，而不是只停留在命令行 demo。
- 后端选择 FastAPI：因为 Python 生态更适合接 LangGraph、RAG、向量库和评估脚本，同时 FastAPI 自带 OpenAPI 文档，适合做服务化接口。
- Agent 编排选择 LangGraph：因为项目不是简单聊天，而是包含 SQL、RAG、Hybrid 路由、失败修复、人工确认等多分支流程，LangGraph 的 StateGraph 和 Conditional Edge 更适合做可控流程。
- 数据库先选择 SQLite：因为 demo 阶段轻量、可复现、方便面试官本地运行；后续可以平滑换成 PostgreSQL。
- 向量库选择 Chroma 或 FAISS：因为本地开发简单，不依赖云服务，适合完成 RAG 检索和引用证据展示。
- 评估集选择 JSONL：因为方便批量运行测试，记录 `question`、`expected_route`、`expected_tools`、`expected_answer_keywords` 等字段。

这个项目真正要证明的不是“我有企业内部数据”，而是：

```text
我知道企业 Agent 怎么接数据；
我知道结构化数据和非结构化知识怎么分开处理；
我知道怎么做工具调用、校验、失败修复；
我知道怎么记录 trace 和评估效果；
我能用 Next.js 做出可交互、可演示的工程产品。
```

## 目标定位

你的已有优势是 Next.js + React 前端实习经历，所以不要把自己包装成纯算法研究岗，而是定位为：

```text
Next.js / React + AI Agent 应用开发实习生
```

20 天的目标不是把所有框架都学完，而是做出一个能投递、能演示、能讲清楚工程细节的项目：

```text
企业数据分析 Copilot
```

一句话描述：

```text
基于 Next.js + FastAPI + LangGraph 的企业数据分析 Agent，支持自然语言查询结构化数据库和非结构化知识库，能自动路由任务、调用工具、生成 SQL、执行校验、引用文档证据、失败反思修复，并提供执行链路、评估指标和运维观测面板。
```

## 项目能力清单

这个项目要体现企业真实 Agent 开发要求：

- Agent 底层机制：Function Calling、ReAct、工具调用、上下文管理。
- LangGraph 工程能力：StateGraph、Node、Edge、Conditional Edge、Checkpointer。
- Text2SQL 能力：schema retrieval、SQL 生成、SQL 只读校验、执行失败修复。
- RAG 能力：文档加载、chunk、embedding、向量检索、引用证据。
- 工程化能力：FastAPI 服务化、Next.js 前端、Docker、日志、trace、测试。
- 可评估能力：eval dataset、任务完成率、工具调用准确率、平均耗时、bad case 分析。
- 可演示能力：聊天界面、执行链路面板、工具调用面板、SQL 展示、文档引用、指标 dashboard。

## 推荐技术栈

```text
前端：
Next.js / React / TypeScript / Tailwind CSS / shadcn/ui / Zustand

后端：
Python / FastAPI / LangGraph / Pydantic / SQLAlchemy

数据层：
SQLite 或 PostgreSQL
Chroma 或 FAISS

Agent：
LangGraph StateGraph
Tool Calling
Checkpointer
RAG
Text2SQL
Reflection Node
Human-in-the-loop Approval

工程化：
Docker Compose
结构化日志
Trace ID
Eval Harness
单元测试
API 文档
```

## 项目目录建议

```text
enterprise-data-copilot/
  apps/
    web/
      app/
      components/
      lib/
      stores/
    api/
      app/
        main.py
        graph/
        tools/
        rag/
        sql/
        memory/
        observability/
        eval/
  data/
    demo.db
    documents/
    eval_dataset.jsonl
  docs/
    architecture.md
    eval_report.md
    bad_cases.md
  docker-compose.yml
  README.md
```

## Agent 工作流设计

```text
START
→ classify_intent
→ route_task
   → sql_subgraph
      → retrieve_schema
      → generate_sql
      → validate_sql
      → execute_sql
      → reflect_sql_error
   → rag_subgraph
      → retrieve_docs
      → rerank_docs
      → generate_doc_answer
   → hybrid_subgraph
      → run_sql
      → run_rag
      → merge_evidence
→ confidence_check
→ ask_clarification / final_answer
→ END
```

## 第 1 天：项目定位和环境搭建

### 学习目标

- 明确企业 Agent 应用开发岗位到底看什么。
- 明确自己不是走纯算法路线，而是走全栈 Agent 应用路线。
- 搭好项目基础环境。

### 要做的事

- 阅读 5-10 个 Agent/RAG/大模型应用开发实习 JD，提炼岗位关键词。
- 确定项目名称：企业数据分析 Copilot。
- 画出第一版系统架构图。
- 初始化 monorepo 项目结构。
- 初始化前端 Next.js 项目。
- 初始化后端 FastAPI 项目。
- 准备 `.env.example`。
- 写 README 初稿。

### 今日产出

- 项目仓库。
- README 初版。
- 技术选型文档。
- 架构草图。

### 验收标准

- 能清楚说出项目解决什么问题。
- 前端和后端项目都能本地启动。
- README 里已经写明技术栈和项目目标。

## 第 2 天：Function Calling 底层机制

### 学习目标

- 搞懂 LLM 不是自己执行工具，而是输出结构化参数。
- 理解 tool schema 对模型行为的影响。
- 掌握工具输入校验和工具输出结构化。

### 要做的事

- 写一个不用任何 Agent 框架的 mini agent。
- 手动定义 2-3 个工具，例如 `calculator`、`get_table_schema`、`query_mock_data`。
- 手动写工具 schema。
- 手动解析模型返回的 tool call。
- 手动执行工具函数。
- 手动把 tool result 塞回 messages。
- 对错误参数做 Pydantic 校验。

### 今日产出

- `mini_agent.py`
- `tools_schema_examples.md`

### 验收标准

- 能解释 function calling 的完整链路。
- 能解释为什么工具描述写得差会导致模型传错参数。
- mini agent 能成功完成至少 3 个工具调用任务。

## 第 3 天：ReAct 循环和失败控制

### 学习目标

- 理解 ReAct 循环：Thought、Action、Observation。
- 理解死循环、早停、上下文爆炸是怎么产生的。
- 学会用工程手段控制 Agent 行为。

### 要做的事

- 给 mini agent 加循环机制。
- 加 `max_iterations`。
- 加工具调用失败重试。
- 加统一错误格式。
- 加 early stop 判断。
- 记录每轮调用的 observation。
- 写 5 个故意失败的 case，观察 Agent 怎么崩。

### 今日产出

- `react_loop.py`
- `bad_cases_react.md`

### 验收标准

- Agent 不会无限循环。
- 工具失败时能返回结构化错误。
- 能说出 ReAct 在真实业务中最常见的 3 类问题。

## 第 4 天：FastAPI 后端骨架

### 学习目标

- 把 Agent 能力服务化。
- 学会用 API 形式提供聊天和运行状态。
- 为后续前后端联调打基础。

### 要做的事

- 创建 FastAPI 项目。
- 实现 `/health`。
- 实现 `/api/chat`。
- 定义 Pydantic 请求和响应模型。
- 实现统一错误返回格式。
- 配置 CORS。
- 接入 mock agent。
- 生成 OpenAPI 文档。

### 今日产出

- FastAPI 基础服务。
- `/health` 和 `/api/chat` 可用。
- API schema 初版。

### 验收标准

- 使用 curl 或 Swagger 能调通 `/api/chat`。
- 后端能返回 mock agent 答案。
- 错误响应格式统一。

## 第 5 天：Next.js Chat UI

### 学习目标

- 把已有前端能力转化成 Agent 产品能力。
- 做出可演示的聊天界面。
- 建立前后端联调能力。

### 要做的事

- 搭建 Next.js 页面结构。
- 实现左侧会话列表。
- 实现中间聊天区。
- 实现用户消息和 assistant 消息展示。
- 实现 loading、error、retry 状态。
- 调用 FastAPI `/api/chat`。
- 保存本地会话状态。

### 今日产出

- 可用聊天页面。
- 前后端联调成功。

### 验收标准

- 用户可以在前端输入问题。
- 前端能展示后端返回内容。
- 请求失败时有明确的错误状态和重试入口。

## 第 6 天：LangGraph 入门

### 学习目标

- 掌握 LangGraph 的最小工作流。
- 理解 State、Node、Edge、END。
- 把 mock agent 替换成 LangGraph workflow。
- 初步建立“多角色节点协作”的意识：先用节点表达不同职责，不急着堆复杂 Multi-Agent。

### 要做的事

- 定义 `AgentState`。
- 写 `classify_intent` 节点。
- 写 `generate_answer` 节点。
- 写 `finalize_response` 节点。
- 用普通边串起来。
- 在 FastAPI 中调用 LangGraph workflow。
- 在设计文档中标出后续会拆分出的核心角色：
  - `RouterAgent`：判断 SQL / RAG / Hybrid / Clarification。
  - `SQLAgent`：负责结构化数据查询。
  - `RAGAgent`：负责文档检索和引用证据。
  - `MemoryAgent`：负责多轮上下文和摘要，先预留。
  - `EvaluatorAgent`：负责答案质量检查，先预留。

### 今日产出

- 第一个 LangGraph workflow。
- 后端 `/api/chat` 使用 LangGraph 返回答案。
- `docs/agent_roles.md`：记录多角色节点职责，不要求当天全部实现。

### 验收标准

- 能画出当前 graph。
- 能解释 State 在节点之间怎么传递。
- 前端调用的已经是 LangGraph 后端。
- 能解释为什么先用 LangGraph 节点表达多角色协作，而不是一开始就做复杂 Multi-Agent。

## 第 7 天：Conditional Edge 和任务路由

### 学习目标

- 掌握 Agent 流程控制的核心。
- 用条件边控制 SQL、RAG、追问三类路径。
- 让 Agent 不再是线性脚本。
- 让 `RouterAgent` 成为项目的第一个明确角色节点。

### 要做的事

- 给 `AgentState` 增加字段：
  - `intent`
  - `route`
  - `error_count`
  - `need_clarification`
  - `is_finished`
- 实现 `route_task` 条件边。
- 路由到 `sql_entry`、`rag_entry`、`ask_clarification`。
- 写 10 个问题测试路由效果。
- 增加 `hybrid` 路由，为后续 SQL + RAG 混合问题做准备。
- 记录每次路由的决策理由，例如为什么查数据库、为什么查文档、为什么两者都查、为什么需要追问。

### 今日产出

- 可路由 LangGraph Agent。
- `routing_test_cases.md`。
- `router_decision_examples.md`。

### 验收标准

- SQL 类问题能进入 SQL 分支。
- 文档类问题能进入 RAG 分支。
- 模糊问题能进入追问分支。
- 能解释 conditional edge 为什么是 Agent 工程核心。
- 能解释 RouterAgent 如何降低模型“随便调用工具”的风险。

## 第 8 天：数据库和 Text2SQL 工具

### 学习目标

- 做出结构化数据查询能力。
- 掌握 Text2SQL Agent 的工具设计。
- 确保 SQL 执行安全。

### 要做的事

- 准备 demo 数据库，可以用电商、SaaS、课程平台、招聘数据等场景。
- 创建 5-8 张表。
- 写入 100-500 条模拟数据。
- 实现工具：
  - `list_tables`
  - `get_table_schema`
  - `sample_rows`
  - `execute_sql_readonly`
- 给 SQL 执行器加只读限制，只允许 `SELECT`。
- 禁止 `DROP`、`DELETE`、`UPDATE`、`INSERT`、`ALTER`。

### 今日产出

- `demo.db`
- SQL tools。
- SQL 安全校验函数。

### 验收标准

- Agent 能查询表结构。
- Agent 能读取样例行。
- 非只读 SQL 会被拒绝。

## 第 9 天：SQL Agent 子图

### 学习目标

- 完成 Text2SQL 主流程。
- 学会把生成、校验、执行、修复拆成节点。
- 初步实现失败反思修复。

### 要做的事

- 实现 `retrieve_schema` 节点。
- 实现 `generate_sql` 节点。
- 实现 `validate_sql` 节点。
- 实现 `execute_sql` 节点。
- 实现 `reflect_sql_error` 节点。
- 用条件边控制：
  - SQL 成功则进入答案生成。
  - SQL 失败且未超重试次数则进入修复。
  - SQL 失败且超过重试次数则返回失败说明。

### 今日产出

- SQL subgraph。
- 失败自动修复一轮。

### 验收标准

- 至少 20 个 SQL 测试问题能跑通。
- SQL 错误时能拿到错误信息并修正一次。
- 能解释为什么 SQL 执行反馈对 Agent 优化很重要。

## 第 10 天：RAG 基础

### 学习目标

- 做出非结构化文档问答能力。
- 掌握 RAG 的基本链路。
- 输出答案时带引用证据。
- 为后续检索增强预留 Multi Query 和相邻 chunk 扩展接口。

### 要做的事

- 准备 10-20 篇业务文档。
- 文档可以是：
  - 产品规则
  - 退款政策
  - 指标口径
  - 数据字段说明
  - 运营 SOP
- 实现文档加载。
- 实现 chunk。
- 生成 embedding。
- 建立 Chroma 或 FAISS 向量库。
- 实现 `retrieve_docs`。
- 实现 `generate_answer_with_citations`。
- 在检索结果中保留 `doc_id`、`chunk_id`、`prev_chunk_id`、`next_chunk_id`、`score`、`metadata`。
- 先实现一个简单的相邻 chunk 扩展策略：命中某个 chunk 后，可选带上前后相邻片段，避免上下文断裂。

### 今日产出

- RAG pipeline。
- 文档引用答案。
- `rag_design.md`：记录 chunk、metadata、citation、相邻 chunk 扩展设计。

### 验收标准

- 文档类问题能返回答案。
- 答案能展示引用来源。
- 检索结果包含文档标题、片段、score、metadata。
- 能解释为什么相邻 chunk 扩展可以缓解“只召回半句话”的问题。

## 第 11 天：Hybrid Agent

### 学习目标

- 让 Agent 同时处理结构化和非结构化信息。
- 实现 SQL + RAG 的结果融合。
- 让项目难度明显高于普通 demo。
- 明确 SQLAgent 和 RAGAgent 的职责边界，形成多角色协作雏形。

### 要做的事

- 增加 `hybrid` 路由。
- 对混合问题同时执行 SQL 和 RAG。
- 实现 `merge_evidence` 节点。
- 将 SQL 流程和 RAG 流程拆成两个子图或两个独立模块：
  - `SQLAgent`：生成 SQL、校验 SQL、执行 SQL、失败修复。
  - `RAGAgent`：检索文档、扩展上下文、生成带引用答案。
- 在 `merge_evidence` 中记录两个 Agent 各自的输入、输出和置信度。
- 最终答案同时包含：
  - 数据库查询结果
  - 文档引用证据
  - 推理说明
- 写 10 个混合问题。

### 今日产出

- SQL + RAG 混合问答能力。
- `hybrid_test_cases.md`。
- SQLAgent / RAGAgent 职责说明和调用链路。

### 验收标准

- 能回答既需要数据又需要规则的问题。
- 前端能展示 SQL 结果和文档证据。
- 能解释什么时候应该走 hybrid 分支。
- 能解释 SQLAgent 和 RAGAgent 为什么要拆开，而不是让一个大 prompt 直接做完。

## 第 12 天：Memory 和 Checkpointer

### 学习目标

- 做出多轮会话和断点恢复能力。
- 理解短期记忆、长期记忆、系统知识的区别。
- 掌握 LangGraph checkpointer 的价值。
- 借鉴多层记忆思路，但收敛成适合本项目的三层记忆：`recent_turns`、`conversation_summary`、`user_profile`。

### 要做的事

- 给每个会话生成 `thread_id`。
- 接入 LangGraph checkpointer。
- 保存每次运行状态。
- 前端支持会话切换。
- 支持刷新页面后继续对话。
- 实现短期记忆：最近几轮消息。
- 设计长期记忆接口，暂时可以先 mock。
- 实现三层记忆结构：
  - `recent_turns`：保留最近几轮完整对话，解决连续追问。
  - `conversation_summary`：当历史变长时压缩成摘要，降低上下文长度。
  - `user_profile`：记录用户角色和偏好，例如“运营同学更关注退款率和客服工单原因”。
- 设计 `MemoryAgent` 节点：
  - 对用户问题做指代补全，例如“那鞋靴类呢？”要继承上一轮时间范围和分析口径。
  - 在回答结束后更新摘要和用户画像。
- 准备 5 个多轮对话 case 测试记忆能力。

### 今日产出

- 多会话持久化。
- 断点恢复 demo。
- 三层记忆数据结构。
- `memory_test_cases.md`。

### 验收标准

- 刷新页面后会话不丢。
- 同一 `thread_id` 能继续上下文。
- 能回答面试问题：Agent 跑到一半崩了怎么恢复。
- 能回答面试问题：recent_turns、summary、user_profile 分别解决什么问题。
- 能演示一次连续追问，例如“4 月服装类退款率”之后再问“那鞋靴类呢？”。

## 第 13 天：Observability 可观测性

### 学习目标

- 让 Agent 出问题时能定位。
- 把执行链路可视化。
- 记录成本、耗时、工具输入输出。
- 让多角色节点的决策过程可解释：Router、SQL、RAG、Memory、Evaluator 都要能被 trace。

### 要做的事

- 每次运行生成 `run_id` 和 `trace_id`。
- 记录每个节点：
  - `node_name`
  - `input_state`
  - `output_state`
  - `latency_ms`
  - `error`
- 记录每次工具调用：
  - `tool_name`
  - `tool_input`
  - `tool_output`
  - `success`
  - `latency_ms`
- 记录角色级 trace：
  - `agent_role`
  - `decision_reason`
  - `confidence`
  - `retrieved_chunks`
  - `generated_sql`
  - `retry_count`
- 前端新增 Trace 面板。
- 前端展示执行步骤时间线。
- Trace 面板按角色分组展示：Router 决策、SQLAgent 查询链路、RAGAgent 检索链路、MemoryAgent 更新内容、EvaluatorAgent 检查结果。

### 今日产出

- 运行链路可视化。
- 工具调用详情面板。
- 角色级 Agent Trace 面板。

### 验收标准

- 任意一次回答都能追踪每个节点。
- 工具调用输入输出可查看。
- 出错时能定位是哪一个节点或工具失败。
- 能解释 trace 如何帮助分析 Agent 回答质量，而不只是打印日志。

## 第 14 天：Human-in-the-loop 审批

### 学习目标

- 加入企业场景中的安全控制。
- 理解高风险操作为什么需要人工确认。
- 体现 Agent 工程不是让模型随便执行。

### 要做的事

- 设计人工审批节点 `approval_required`。
- 对敏感 SQL 或高成本操作触发审批。
- 前端展示 approve / reject 操作。
- 后端根据用户选择继续或终止。
- 记录审批结果。

### 今日产出

- 人工确认节点。
- 审批式 Agent 流程。

### 验收标准

- 触发审批时 Agent 会暂停。
- 用户批准后继续执行。
- 用户拒绝后终止并说明原因。

## 第 15 天：评估集设计

### 学习目标

- 从 demo 进入可评估项目。
- 学会设计能判断对错的测试集。
- 为简历准备量化指标。
- 让评估集同时覆盖路由、SQL、RAG、Hybrid、记忆和追问。

### 要做的事

- 写 80-100 条 eval case。
- 分类：
  - SQL 查询题
  - 文档问答题
  - 混合推理题
  - 需要追问的问题
  - 故意包含歧义的问题
  - 多轮记忆题
  - 检索增强题
- 每条包含：
  - `question`
  - `expected_route`
  - `expected_tools`
  - `expected_sql` 可选
  - `expected_answer_keywords`
  - `expected_citations` 可选
  - `conversation_context` 可选
  - `difficulty`
- 定义评估指标。

### 今日产出

- `eval_dataset.jsonl`
- `eval_metrics.md`
- `golden_test_set.md`

### 验收标准

- 至少 80 条测试样本。
- 每条样本都能判断是否成功。
- 指标定义清楚，不是只看主观感觉。
- 能解释为什么 Agent 项目必须评估 route、tool、citation 和 answer，而不是只看答案像不像。

## 第 16 天：Eval Harness 自动评估

### 学习目标

- 自动跑评估，不靠手工点页面。
- 记录结果并生成报告。
- 形成面试时能讲的优化闭环。
- 预留 Ragas / Custom Evaluator 接口，但第一版优先实现自定义评估。

### 要做的事

- 写 `run_eval.py`。
- 批量读取 `eval_dataset.jsonl`。
- 自动调用 Agent。
- 记录每条结果。
- 计算指标：
  - `task_success_rate`
  - `sql_execution_success_rate`
  - `tool_call_accuracy`
  - `route_accuracy`
  - `citation_hit_rate`
  - `memory_followup_success_rate`
  - `avg_latency`
  - `avg_tool_calls`
  - `retry_success_rate`
- 生成 `eval_report.md`。
- 设计 evaluator 插件接口：
  - 第一版使用规则和关键词判断。
  - 后续可以接 Ragas 评估 faithfulness、context_precision、answer_relevancy。

### 今日产出

- 自动评估脚本。
- 第一版评估报告。
- evaluator 接口草稿。

### 验收标准

- 一条命令能跑完整评估。
- 能得到 baseline 指标。
- 评估结果保存为 JSON 和 Markdown。
- 能解释为什么第一版先用 Custom Evaluator，而不是直接重度依赖 Ragas。

## 第 17 天：优化一轮并记录对比

### 学习目标

- 学会根据 bad case 做针对性优化。
- 拿到优化前后对比数据。
- 准备简历最有说服力的项目亮点。
- 加入 1-2 个高级但可讲清楚的优化点，而不是堆满所有技术名词。

### 要做的事

- 分析 baseline bad cases。
- 优化 SQL schema retrieval。
- 优化工具描述。
- 优化 RAG chunk size 和 top-k。
- 实现 Query Rewrite / Multi Query：把用户问题扩展成 2-3 个检索查询，提高文档召回。
- 优化相邻 chunk 扩展策略：对命中文档片段补充前后片段，并观察 citation 质量变化。
- 给 SQL 生成加入 few-shot 示例。
- 给错误修复节点补充失败原因。
- 再跑一轮 eval。
- 写优化前后对比表。

### 今日产出

- `bad_cases.md`
- `optimization_report.md`
- baseline vs optimized 对比结果。
- Multi Query / 相邻 chunk 扩展前后对比。

### 验收标准

- 至少找到 5 类 bad case。
- 至少完成 3 项针对性优化。
- 指标有可解释的提升。
- 能清楚说明每个优化点解决了哪类 bad case，而不是为了堆技术词。

## 第 18 天：工程化收尾

### 学习目标

- 让项目像真实工程，而不是临时 demo。
- 确保别人 clone 后能跑。
- 补齐测试、配置、部署能力。

### 要做的事

- 写 Dockerfile。
- 写 docker-compose。
- 补 `.env.example`。
- 写后端单元测试：
  - SQL 只读校验
  - 工具参数校验
  - 路由逻辑
  - eval 指标计算
- 写前端基础构建检查。
- 补 API 文档。
- 检查 README 运行步骤。

### 今日产出

- Docker Compose 一键启动。
- 基础测试。
- 工程化 README。

### 验收标准

- 项目可以通过 Docker 启动。
- 后端基础测试通过。
- README 中的启动命令真实可用。

## 第 19 天：项目包装和面试材料

### 学习目标

- 把项目包装成能投递的作品。
- 准备面试讲解材料。
- 把工程亮点讲成企业听得懂的话。

### 要做的事

- 完善 README。
- 补架构图。
- 录制 1-2 分钟 demo 视频或 GIF。
- 整理截图：
  - 聊天页面
  - Trace 面板
  - SQL 工具调用
  - 文档引用
  - Eval dashboard
- 写 `interview_script.md`。
- 准备项目常见追问答案。

### 今日产出

- GitHub 可投递版本。
- 项目讲解稿。
- demo GIF 或视频。

### 验收标准

- 面试官 2 分钟能看懂项目价值。
- README 能体现 Agent、工程化、评估三条线。
- 你能用 3-5 分钟讲清楚项目架构。

## 第 20 天：简历优化和集中投递

### 学习目标

- 把项目转化为实习竞争力。
- 明确投递岗位和话术。
- 开始拿面试机会。

### 要做的事

- 修改简历项目描述。
- 准备 2 个版本：
  - AI Agent 应用开发版
  - AIGC 前端 / AI 产品工程版
- 投递岗位：
  - AI Agent 应用开发实习生
  - 大模型应用开发实习生
  - RAG 工程实习生
  - LLM Full-stack Intern
  - AIGC 前端工程实习生
  - AI 产品工程实习生
- 每天投递 15-30 个。
- 主动私信技术负责人或招聘方。

### 今日产出

- 简历新版。
- 投递记录表。
- 项目私信模板。

### 验收标准

- 简历中有一个完整 Agent 工程项目。
- GitHub 项目能打开、能跑、能看指标。
- 开始批量投递并记录反馈。

## 简历项目描述模板

```text
企业数据分析 Copilot | Next.js, FastAPI, LangGraph, RAG, Text2SQL

基于 LangGraph 设计 SQL/RAG/Hybrid 多路径 Agent 工作流，支持自然语言查询结构化数据库和企业知识库。实现工具调用、SQL 只读校验、执行失败反思修复、Checkpointer 会话恢复和人工审批节点。前端基于 Next.js 实现聊天、Agent 执行链路、工具调用、SQL、文档证据和评估指标可视化。构建 100 条评测集，记录任务完成率、SQL 执行成功率、工具调用准确率、平均耗时和修复成功率，并通过 schema linking 和检索优化提升整体成功率。
```

## 投递私信模板

```text
您好，我之前有 Next.js + React 前端实习经历，最近在做 AI Agent 应用开发方向。

我做了一个基于 Next.js + FastAPI + LangGraph 的企业数据分析 Copilot，支持 Text2SQL、RAG、SQL/RAG 混合路由、工具调用、执行失败反思修复、Checkpointer 会话恢复和 Trace 可视化，并构建了评估集记录任务完成率、工具调用准确率、平均耗时等指标。

想投递贵团队 AI Agent / 大模型应用开发 / RAG 工程方向实习，如果方便的话，希望能获得一次交流机会。
```

## 面试高频问题清单

- Function Calling 的真实执行流程是什么？
- LLM 是怎么知道该调用哪个工具的？
- ReAct 循环为什么会死循环？
- Agent 早停怎么处理？
- 上下文爆炸怎么处理？
- LangGraph 的 State、Node、Edge 分别是什么？
- Conditional Edge 怎么设计？
- Checkpointer 解决什么问题？
- Agent 跑到一半崩了怎么恢复？
- Tool schema 怎么写才稳定？
- SQL 工具为什么必须做只读校验？
- RAG 为什么会召回错？
- RAG 怎么评估？
- Memory 应该怎么分层？
- 怎么记录 Agent 的执行链路？
- 你的项目如何评估效果？
- 你做过哪些 bad case 优化？
- 为什么不用 Multi-Agent？
- 为什么这个项目比普通 demo 更接近企业场景？

## 20 天内暂时不要主攻的方向

- Multi-Agent 大规模协作。
- AutoGen / CrewAI 横向刷框架。
- SFT / RLHF / PPO / GRPO。
- 多模态 Agent。
- 从零训练模型。
- 复杂 Kubernetes 部署。

这些可以了解概念，但不要抢占主线时间。

## 最终验收标准

20 天结束时，你应该至少拥有：

- 一个完整 GitHub 项目。
- 一个 Next.js 前端演示页面。
- 一个 FastAPI + LangGraph 后端。
- SQL Agent 子流程。
- RAG Agent 子流程。
- Hybrid 路由能力。
- RouterAgent / SQLAgent / RAGAgent / MemoryAgent / EvaluatorAgent 的多角色节点设计，其中 MemoryAgent 和 EvaluatorAgent 可以是轻量实现。
- recent_turns、conversation_summary、user_profile 三层记忆机制。
- Query Rewrite / Multi Query 或相邻 chunk 扩展中的至少一个 RAG 优化点。
- Checkpointer 会话恢复。
- Trace 可视化。
- Eval Harness 自动评估。
- 80-100 条评估集。
- README、架构图、demo、评估报告、bad case 报告。
- 一版能投递 AI Agent 应用开发实习的简历。

## 核心竞争力总结

你要让面试官记住的是：

```text
我不只是会调模型 API，也不只是会写前端页面。
我能把 Agent 做成一个有状态、有工具、有评估、有日志、有恢复能力、能真实演示的工程化产品。
```

升级后的项目亮点可以概括为：

```text
我用 LangGraph 把电商售后分析拆成 RouterAgent、SQLAgent、RAGAgent、MemoryAgent 和 EvaluatorAgent 等多角色节点；
用 Text2SQL 处理订单、商品、退款、评价、客服工单等结构化数据；
用 RAG 检索退款政策、售后 SOP、指标口径等非结构化文档；
用 recent_turns、conversation_summary、user_profile 支持连续追问；
用 Trace Dashboard 和 Eval Harness 分析路由、工具调用、文档引用和答案质量。
```
