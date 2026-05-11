# 电商售后数据分析 Copilot

这是一个面向 AI Agent 应用开发实习投递的全栈工程项目。项目目标不是做一个泛泛聊天机器人，而是做一个能处理电商售后业务问题的业务分析助手：用户用自然语言提问，系统自动判断是否需要查询结构化数据库、检索非结构化业务文档，或同时执行两条路径，最后给出带数据、证据、执行链路和评估指标的回答。

## 项目定位

用户示例问题：

```text
4 月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。
```

系统预期流程：

```text
自然语言问题
-> 任务分类与路由
-> SQL 分支查询订单、商品、退款、评价、客服工单等数据
-> RAG 分支检索退款政策、售后 SOP、指标口径等文档
-> 合并结构化数据和文档证据
-> 输出分析结论、SQL、引用来源、执行链路、耗时和工具调用记录
```

## 为什么使用模拟数据

本项目使用模拟电商售后业务数据，重点验证 Agent 在结构化数据查询、非结构化知识检索、工具调用、执行链路追踪和自动评估上的工程能力。真实落地时，只需要替换数据库连接、业务文档和权限系统即可。

## 技术栈

```text
前端：Next.js / React / TypeScript / Tailwind CSS
后端：Python / FastAPI / Pydantic
Agent：LangGraph / Tool Calling / Text2SQL / RAG
数据：SQLite / Chroma 或 FAISS
工程化：Docker Compose / 结构化日志 / Trace ID / Eval Harness
```

## 当前进度

第 1 天已完成项目定位和基础骨架：

- 初始化 monorepo 目录结构。
- 创建 Next.js 前端骨架。
- 创建 FastAPI 后端骨架。
- 补充环境变量示例。
- 补充技术选型文档。
- 补充系统架构草图。
- 使用 Git 管理项目。

## 目录结构

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
        api/
        core/
        schemas/
        services/
  data/
    documents/
  docs/
    architecture.md
    day-1-jd-keywords.md
    tech-selection.md
  scripts/
  .env.example
  package.json
```

## 本地启动

前端依赖安装后启动：

```bash
npm install
npm run dev:web
```

后端依赖安装后启动：

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

当前第 1 天主要完成项目骨架。后续会逐步接入真实 LangGraph workflow、SQL tools、RAG pipeline、trace 面板和自动评估脚本。
