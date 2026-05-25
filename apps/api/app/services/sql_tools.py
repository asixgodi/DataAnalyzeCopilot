import re
import sqlite3
from typing import Any

from app.schemas.chat import SqlResult
from app.services.data_store import get_connection


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
