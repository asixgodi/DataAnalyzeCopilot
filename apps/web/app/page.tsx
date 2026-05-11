import { getApiBaseUrl } from "@/lib/api";

const capabilityGroups = [
  {
    title: "业务入口",
    items: ["自然语言提问", "售后数据分析", "退款原因归因"]
  },
  {
    title: "Agent 能力",
    items: ["SQL 路由", "RAG 检索", "Hybrid 合并", "失败修复"]
  },
  {
    title: "工程化",
    items: ["Trace 链路", "评估指标", "可恢复会话", "API 服务化"]
  }
];

export default function HomePage() {
  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Enterprise Agent Project</p>
          <h1>电商售后数据分析 Copilot</h1>
          <p className="summary">
            面向电商售后场景的 AI Agent：把自然语言问题路由到 SQL、RAG 或混合分析流程，
            并展示数据结果、文档证据、执行链路和评估指标。
          </p>
        </div>
        <div className="statusBox">
          <span>API Base URL</span>
          <strong>{getApiBaseUrl()}</strong>
        </div>
      </section>

      <section className="questionPanel">
        <p className="panelLabel">示例问题</p>
        <h2>4 月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。</h2>
      </section>

      <section className="grid">
        {capabilityGroups.map((group) => (
          <article className="card" key={group.title}>
            <h3>{group.title}</h3>
            <ul>
              {group.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>
    </main>
  );
}
