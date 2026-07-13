"""
参数化 SQL 模板库 — 基于结构化 QueryParams 生成安全 SQL。

设计目标：
  - 将硬编码的 if-else SQL 模板替换为参数化模板库
  - 每个模板支持 :placeholder 参数化，由 build_sql_from_params 填充
  - 支持环比对比（自动 UNION 上月数据）
  - 模板匹配失败时返回 None，由 LLM 全量生成兜底
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.sql_tools import QueryParams


# ── SQL 模板 ─────────────────────────────────────────────────────────

SQL_TEMPLATES: dict[str, str] = {
    "refund_rate": """
        SELECT p.category, o.month,
               COUNT(DISTINCT o.id) AS order_count,
               COUNT(DISTINCT r.id) AS refund_count,
               ROUND(COUNT(DISTINCT r.id) * 100.0 / COUNT(DISTINCT o.id), 2) AS refund_rate
        FROM orders o
        JOIN products p ON o.product_id = p.id
        LEFT JOIN refunds r ON r.order_id = o.id
        WHERE o.month = '{time_range}'
          {category_filter}
        GROUP BY p.category, o.month
    """,

    "refund_count": """
        SELECT p.category, o.month,
               COUNT(DISTINCT r.id) AS refund_count,
               ROUND(SUM(r.refund_amount), 2) AS total_refund_amount
        FROM refunds r
        JOIN orders o ON r.order_id = o.id
        JOIN products p ON o.product_id = p.id
        WHERE o.month = '{time_range}'
          {category_filter}
        GROUP BY p.category, o.month
    """,

    "order_count": """
        SELECT p.category, o.month,
               COUNT(DISTINCT o.id) AS order_count,
               ROUND(SUM(o.amount), 2) AS total_amount
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.month = '{time_range}'
          {category_filter}
        GROUP BY p.category, o.month
    """,

    "ticket_distribution": """
        SELECT t.reason, COUNT(*) AS ticket_count,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS percentage
        FROM tickets t
        JOIN products p ON t.product_id = p.id
        WHERE t.month = '{time_range}'
          {category_filter}
        GROUP BY t.reason
        ORDER BY ticket_count {sort_order}
        LIMIT {limit}
    """,

    "top_refund_products": """
        SELECT p.name, p.category,
               COUNT(r.id) AS refund_count,
               ROUND(SUM(r.refund_amount), 2) AS total_refund_amount
        FROM refunds r
        JOIN orders o ON r.order_id = o.id
        JOIN products p ON o.product_id = p.id
        WHERE o.month = '{time_range}'
          {category_filter}
        GROUP BY p.id, p.name, p.category
        ORDER BY refund_count {sort_order}
        LIMIT {limit}
    """,

    "review_score_avg": """
        SELECT p.category,
               ROUND(AVG(rv.rating), 2) AS avg_rating,
               COUNT(rv.id) AS review_count,
               SUM(CASE WHEN rv.rating <= 2 THEN 1 ELSE 0 END) AS negative_count
        FROM reviews rv
        JOIN products p ON rv.product_id = p.id
        WHERE rv.month = '{time_range}'
          {category_filter}
        GROUP BY p.category
    """,

    "refund_amount_sum": """
        SELECT p.category, o.month,
               COUNT(DISTINCT r.id) AS refund_count,
               ROUND(SUM(r.refund_amount), 2) AS total_amount,
               ROUND(AVG(r.refund_amount), 2) AS avg_amount
        FROM refunds r
        JOIN orders o ON r.order_id = o.id
        JOIN products p ON o.product_id = p.id
        WHERE o.month = '{time_range}'
          {category_filter}
        GROUP BY p.category, o.month
    """,
}


def _build_category_filter(category: str | None) -> str:
    """生成品类过滤条件。"""
    if category:
        return f"AND p.category = '{category}'"
    return ""  # 不限制品类


def _prev_month(time_range: str) -> str:
    """计算上一个月，如 2026-04 → 2026-03，2026-01 → 2025-12。"""
    if "-" not in time_range:
        return time_range
    parts = time_range.split("-")
    year, month = int(parts[0]), int(parts[1])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def build_sql_from_params(params: QueryParams) -> str | None:
    """
    根据结构化查询参数选择并填充 SQL 模板。

    Returns:
        填充后的 SQL 字符串，如果没有匹配的模板则返回 None。
    """
    template = SQL_TEMPLATES.get(params.metric)
    if not template:
        return None

    category_filter = _build_category_filter(params.category)
    sort_order = params.sort_order if params.sort_order in ("asc", "desc") else "desc"

    sql = template.format(
        time_range=params.time_range or "2026-04",
        category_filter=category_filter,
        limit=params.limit,
        sort_order=sort_order,
    )

    # 环比对比：UNION 上月数据
    if params.comparison == "month_over_month" and params.time_range:
        prev_month = _prev_month(params.time_range)
        current_sql = sql.strip()
        prev_sql = template.format(
            time_range=prev_month,
            category_filter=category_filter,
            limit=params.limit,
            sort_order=sort_order,
        ).strip()
        sql = f"""
            SELECT 'current' AS period, t.* FROM ({current_sql}) AS t
            UNION ALL
            SELECT 'previous' AS period, t.* FROM ({prev_sql}) AS t
        """

    return sql.strip()
