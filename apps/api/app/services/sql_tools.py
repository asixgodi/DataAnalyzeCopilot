import logging
import re
import sqlite3
from typing import Any

import sqlparse
from pydantic import BaseModel, Field

from app.schemas.chat import SqlResult
from app.services.data_store import get_connection
from app.services.intent import extract_intent_slots

logger = logging.getLogger(__name__)


BLOCKED_SQL = re.compile(r"\b(drop|delete|update|insert|alter|truncate|replace|create)\b", re.I)

# 敏感字段 — 命中则触发人工审批
SENSITIVE_FIELDS = re.compile(
    r"\b(password|passwd|secret|token|api_key|credit_card|phone|mobile"
    r"|email|id_card|ssn|address|salary|balance)\b",
    re.I,
)
# 高风险表
HIGH_RISK_TABLES = re.compile(r"\b(users|accounts|payments|salary|audit_log)\b", re.I)
# 估算行数阈值
ROW_WARNING = 200
ROW_DANGER = 500


def analyze_sql_risk(sql: str) -> dict[str, Any]:
    """
    SQL 四级风险分析。

    返回: {"level": "safe"|"warning"|"dangerous"|"blocked",
           "reason": str, "risk": str}
    """
    normalized = sql.strip()

    # ── 第 4 级：非 SELECT / 写操作 → 直接拒绝 ──
    if not normalized.lower().startswith("select"):
        return {"level": "blocked", "reason": "非 SELECT 语句，不允许执行。", "risk": "write_operation"}
    if BLOCKED_SQL.search(normalized):
        return {"level": "blocked", "reason": "SQL 包含被禁止的写操作关键字。", "risk": "write_keyword"}

    # ── 第 3 级：敏感字段 → 人工审批 ──
    sensitive_hits = SENSITIVE_FIELDS.findall(normalized.lower())
    if sensitive_hits:
        return {
            "level": "dangerous",
            "reason": f"SQL 涉及敏感字段：{', '.join(set(sensitive_hits))}，需要人工审批后执行。",
            "risk": "sensitive_field",
        }

    # ── 第 2 级：大范围扫描 → 二次确认 ──
    # 检测跨表 JOIN 数量
    join_count = len(re.findall(r"\bJOIN\b", normalized, re.I))
    # 检测是否有 LIMIT
    has_limit = bool(re.search(r"\bLIMIT\b", normalized, re.I))

    if join_count >= 3 and not has_limit:
        return {
            "level": "dangerous",
            "reason": f"SQL 涉及 {join_count} 表 JOIN 且无 LIMIT，可能造成大范围扫描。",
            "risk": "large_scan",
        }

    # ── 第 1 级：潜在性能问题 → 二次确认 ──
    if join_count >= 2 and not has_limit:
        return {
            "level": "warning",
            "reason": f"SQL 涉及 {join_count} 表关联，建议加 LIMIT 限制返回行数。",
            "risk": "no_limit_with_joins",
        }

    # ── 第 0 级：安全 ──
    return {"level": "safe", "reason": "", "risk": "none"}


def validate_readonly_sql(sql: str) -> None:
    normalized = sql.strip().rstrip(";")
    if not normalized.lower().startswith("select"):
        raise ValueError("Only SELECT statements are allowed.")
    if BLOCKED_SQL.search(normalized):
        raise ValueError("Dangerous SQL keyword detected.")


def execute_readonly_sql(sql: str) -> SqlResult:
    validate_readonly_sql(sql)
    conn = get_connection()
    try:
        cursor = conn.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
        columns = [description[0] for description in cursor.description or []]
        return SqlResult(sql=sql, columns=columns, rows=rows, row_count=len(rows))
    except sqlite3.Error as exc:
        return SqlResult(sql=sql, columns=[], rows=[], row_count=0, error=str(exc))
    finally:
        conn.close()


def list_tables() -> list[str]:
    conn = get_connection()
    try:
        return [
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
    finally:
        conn.close()


def get_table_schema(table: str) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def build_sql_for_question(question: str) -> str:
    month = "2026-04"
    if "3月" in question or "2026-03" in question:
        month = "2026-03"
    if "5月" in question or "2026-05" in question:
        month = "2026-05"

    category = "服装"
    if "鞋" in question or "鞋靴" in question:
        category = "鞋靴"
    if "数码" in question or "耳机" in question or "手表" in question:
        category = "数码"

    asks_refund_rate = "退款率" in question
    asks_top = "最高" in question or "top" in question.lower() or "排行" in question or "排名" in question

    if asks_top and not asks_refund_rate:
        return f"""
        SELECT p.name, p.category, COUNT(r.id) AS refund_count, ROUND(SUM(r.refund_amount), 2) AS refund_amount
        FROM refunds r
        JOIN orders o ON r.order_id = o.id
        JOIN products p ON o.product_id = p.id
        WHERE o.month = '{month}'
        GROUP BY p.id, p.name, p.category
        ORDER BY refund_count DESC
        LIMIT 5
        """

    if not asks_refund_rate and ("工单" in question or "客服" in question or "原因" in question):
        return f"""
        SELECT t.reason, COUNT(*) AS ticket_count
        FROM tickets t
        JOIN products p ON t.product_id = p.id
        WHERE t.month = '{month}' AND p.category = '{category}'
        GROUP BY t.reason
        ORDER BY ticket_count DESC
        """

    return f"""
    SELECT p.category,
           o.month,
           COUNT(DISTINCT o.id) AS order_count,
           COUNT(DISTINCT r.id) AS refund_count,
           ROUND(COUNT(DISTINCT r.id) * 100.0 / COUNT(DISTINCT o.id), 2) AS refund_rate
    FROM orders o
    JOIN products p ON o.product_id = p.id
    LEFT JOIN refunds r ON r.order_id = o.id
    WHERE o.month = '{month}' AND p.category = '{category}'
    GROUP BY p.category, o.month
    """


# ── SQL 安全校验 v2 (sqlparse AST) ───────────────────────────────────


def validate_readonly_sql_v2(sql: str) -> None:
    """
    基于 sqlparse AST 的 SQL 安全校验。

    相比 validate_readonly_sql（正则 + 首词检查），
    sqlparse 能正确解析多语句、嵌套子查询、注释等，
    防止 SELECT...; DROP TABLE orders-- 这种绕过。
    """
    statements = sqlparse.parse(sql)

    if len(statements) == 0:
        raise ValueError("SQL 为空。")

    if len(statements) > 1:
        raise ValueError(f"SQL 包含 {len(statements)} 条语句，只允许单条 SELECT。")

    stmt = statements[0]
    stmt_type = stmt.get_type()

    if stmt_type not in ("SELECT", "UNKNOWN"):
        raise ValueError(f"不允许的 SQL 类型：{stmt_type}，只允许 SELECT。")

    # 遍历 token 检查危险关键字
    dangerous_tokens = {
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
        "TRUNCATE", "CREATE", "REPLACE", "ATTACH", "DETACH",
    }
    for token in stmt.flatten():
        if token.ttype in (
            sqlparse.tokens.Keyword,
            sqlparse.tokens.Keyword.DDL,
            sqlparse.tokens.Keyword.DML,
        ):
            if token.normalized.upper() in dangerous_tokens:
                raise ValueError(f"SQL 包含危险关键字：{token.normalized}")


# ── QueryParams — 结构化查询参数 ──────────────────────────────────────


class QueryParams(BaseModel):
    """从用户问题中抽取的结构化查询参数。"""

    time_range: str | None = Field(None, description="时间范围，如 2026-04")
    category: str | None = Field(None, description="商品类目：服装/鞋靴/数码")
    metric: str = Field("refund_rate", description="指标类型")
    # 可选 metric：
    #   refund_rate, refund_count, order_count, ticket_count,
    #   ticket_distribution, top_refund_products,
    #   review_score_avg, refund_amount_sum
    comparison: str | None = Field(None, description="对比维度：month_over_month / year_over_year")
    sort_by: str | None = Field(None, description="排序字段")
    sort_order: str = Field("desc", description="排序方向：asc / desc")
    limit: int = Field(10, description="返回行数限制")


# ── 参数抽取 ─────────────────────────────────────────────────────────


def extract_query_params(question: str) -> QueryParams:
    """
    从自然语言中抽取结构化查询参数。

    策略：规则先行 → LLM 增强 → 规则关键字兜底。避免 LLM 把"退款率"误判为 top_refund_products。
    """
    rule_params = _extract_params_by_rules(question)
    slots = extract_intent_slots(question)
    if slots.metric and slots.confidence >= 0.9:
        return rule_params
    try:
        llm_params = _extract_params_with_llm(question)
    except Exception as exc:
        logger.warning("LLM param extraction failed (%s), using rules", exc)
        return rule_params

    # ── 规则校准：如果问题中明确提到了指标关键词，规则优先 ──
    if slots.metric and llm_params.metric != slots.metric:
        logger.info(
            "Param extraction: overriding LLM metric %s → %s (intent slots)",
            llm_params.metric,
            slots.metric,
        )
        llm_params.metric = slots.metric

    # 时间范围：LLM 通常更准确（处理"上个月"等），但如果 LLM 没抽到则用规则结果
    if not llm_params.time_range:
        llm_params.time_range = rule_params.time_range
    # 品类：规则更可靠
    if not llm_params.category:
        llm_params.category = rule_params.category
    # 对比：合并（规则+LLM）
    if rule_params.comparison and not llm_params.comparison:
        llm_params.comparison = rule_params.comparison

    return llm_params


def _extract_params_with_llm(question: str) -> QueryParams:
    """LLM 参数抽取（依赖 llm_client，避免循环导入延迟导入）。"""
    import json as _json

    from app.services.llm_client import get_llm_client

    prompt = f"""从用户问题中抽取查询参数，只输出 JSON。

可选 metric 值：
- refund_rate: 退款率
- refund_count: 退款数量
- order_count: 订单数量
- ticket_distribution: 工单原因分布
- ticket_count: 工单数量
- top_refund_products: 退款最多的商品
- review_score_avg: 平均评分
- refund_amount_sum: 退款总金额

time_range 格式：YYYY-MM（如 2026-04）；未提到时间则为 null。
category：服装、鞋靴、数码；未提到则为 null。
comparison：month_over_month（环比）、year_over_year（同比）、null。

用户问题：{question}

输出 JSON：{{"time_range":null,"category":null,"metric":"refund_rate","comparison":null,"sort_by":null,"sort_order":"desc","limit":10}}"""

    client = get_llm_client()
    text, _ = client.call(
        [{"role": "user", "content": prompt}],
        purpose="param_extract",
        temperature=0,
        max_tokens=240,
        response_format={"type": "json_object"},
    )

    # 解析 JSON
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = next((p for p in parts if "{" in p and "}" in p), cleaned)
        cleaned = cleaned.replace("json", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM did not return JSON object")
    data = _json.loads(cleaned[start : end + 1])

    data = {k: v for k, v in data.items() if k in QueryParams.model_fields and v is not None}
    return QueryParams(**data)


def _extract_params_by_rules(question: str) -> QueryParams:
    """规则兜底：当 LLM 参数抽取失败时使用。"""
    slots = extract_intent_slots(question)
    return QueryParams(
        time_range=slots.time_range or "2026-04",
        category=slots.category,
        metric=slots.metric or "refund_rate",
        comparison=slots.comparison,
        sort_order="desc",
        limit=10,
    )


# ── SQL 错误分类 ─────────────────────────────────────────────────────


def classify_sql_error(error: str) -> str:
    """
    SQL 执行错误分类，用于结构化 Reflect。

    Returns:
        no_such_column | no_such_table | ambiguous_column |
        syntax | type_mismatch | unknown
    """
    error_lower = error.lower()
    if "no such column" in error_lower:
        return "no_such_column"
    if "no such table" in error_lower:
        return "no_such_table"
    if "ambiguous column" in error_lower:
        return "ambiguous_column"
    if "near" in error_lower or "syntax" in error_lower:
        return "syntax"
    if "datatype" in error_lower or "type mismatch" in error_lower:
        return "type_mismatch"
    return "unknown"
