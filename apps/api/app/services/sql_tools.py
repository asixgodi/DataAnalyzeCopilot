import re
import sqlite3
from typing import Any

from app.schemas.chat import SqlResult
from app.services.data_store import get_connection


BLOCKED_SQL = re.compile(r"\b(drop|delete|update|insert|alter|truncate|replace|create)\b", re.I)


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

    if "最高" in question or "top" in question.lower():
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

    if "工单" in question or "客服" in question or "原因" in question:
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
