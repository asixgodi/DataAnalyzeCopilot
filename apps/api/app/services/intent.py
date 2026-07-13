# 把分散的意图理解逻辑集中到一个模块，输出一个结构化的IntentSlots对象

import re
from typing import Literal

from pydantic import BaseModel, Field


IntentAction = Literal[
    "query_metric",
    "query_ranking",
    "ask_definition",
    "ask_process",
    "analyze_reason",
    "clarify",
]


class IntentSlots(BaseModel):
    action: IntentAction = "clarify"
    metric: str | None = None
    time_range: str | None = None
    category: str | None = None
    comparison: str | None = None
    needs_data: bool = False
    needs_docs: bool = False
    is_followup: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = 0
    reason: str = ""


_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "服装": ("服装", "衣服", "T恤", "裤子", "裙子", "外套", "衬衫"),
    "鞋靴": ("鞋靴", "鞋子", "靴子", "运动鞋", "皮鞋", "凉鞋", "鞋"),
    "数码": ("数码", "手机", "耳机", "手表", "平板", "电脑", "音箱", "手机壳"),
}

_VAGUE_QUESTIONS = {"随便看看", "帮我看看", "不知道", "都行", "看看", "随便"}
_DOC_TERMS = ("政策", "规则", "SOP", "sop", "口径", "定义", "流程", "规范", "证据", "文档")
_PROCESS_TERMS = ("应该", "应当", "触发", "怎么处理", "如何处理", "如何判断", "怎么判断", "处置", "升级", "审核")
_REASON_TERMS = ("为什么", "原因", "归因", "分析", "升高", "上升", "下降", "降低", "异常")


def _extract_time_range(text: str) -> str | None:
    match = re.search(r"(20\d{2})[-年/ ]?(0?[1-9]|1[0-2])月?", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"(?<!\d)([1-9]|1[0-2])月", text)
    if match:
        return f"2026-{int(match.group(1)):02d}"
    chinese_months = {
        "一月": 1, "二月": 2, "三月": 3, "四月": 4, "五月": 5, "六月": 6,
        "七月": 7, "八月": 8, "九月": 9, "十月": 10, "十一月": 11, "十二月": 12,
    }
    for label, month in sorted(chinese_months.items(), key=lambda item: len(item[0]), reverse=True):
        if label in text:
            return f"2026-{month:02d}"
    if re.search(r"上个?月", text):
        return "2026-03"
    return None


def _extract_category(text: str) -> str | None:
    for category, aliases in _CATEGORY_ALIASES.items():
        if any(alias in text for alias in aliases):
            return category
    return None


def _extract_metric(text: str) -> str | None:
    # Explicit business phrases are deliberately mutually exclusive and ordered.
    if any(term in text for term in ("退款率", "退货率", "退款比例", "退款占比")):
        return "refund_rate"
    if any(term in text for term in (
        "退款次数最高", "退款最多", "退货最多", "退款排行", "退款排名",
        "最高的商品", "最多的商品", "top", "TOP",
    )):
        return "top_refund_products"
    if any(term in text for term in ("工单原因", "投诉原因", "工单分布", "原因分布")):
        return "ticket_distribution"
    if any(term in text for term in ("工单数", "工单数量", "多少工单")):
        return "ticket_count"
    if any(term in text for term in ("评分", "好评", "差评", "星级", "平均分")):
        return "review_score_avg"
    if any(term in text for term in ("退款总金额", "总退款金额", "退款金额合计", "退了多少钱")):
        return "refund_amount_sum"
    if re.search(r"退款数(?!据)", text) or any(
        term in text for term in ("退款单数", "退款笔数", "退款数量", "退了多少单")
    ):
        return "refund_count"
    if any(term in text for term in ("订单数", "订单量", "订单数量", "销量", "卖了多少")):
        return "order_count"
    return None

# 核心函数
def extract_intent_slots(question: str) -> IntentSlots:
    text = question.strip()
    normalized = re.sub(r"[\s，。！？?！,.]", "", text)
    if not normalized or normalized in _VAGUE_QUESTIONS:
        return IntentSlots(
            action="clarify",
            missing_fields=["analysis_goal"],
            confidence=0.98,
            reason="问题缺少明确的分析目标。",
        )

    metric = _extract_metric(text)
    time_range = _extract_time_range(text)
    category = _extract_category(text)
    has_definition = any(term in text for term in ("口径", "定义", "怎么算", "如何计算", "含义"))
    has_process = any(term in text for term in _PROCESS_TERMS) or any(
        term in text for term in ("SOP", "sop", "流程", "规则", "政策", "规范")
    )
    has_reason = metric != "ticket_distribution" and any(term in text for term in _REASON_TERMS)
    has_ranking = metric == "top_refund_products"
    has_doc_term = any(term in text for term in _DOC_TERMS)
    has_explicit_data_scope = bool(time_range or category) or any(
        term in text for term in ("查询", "统计", "多少", "实际", "当前", "本月", "上月", "环比", "同比")
    )

    if has_definition:
        action: IntentAction = "ask_definition"
    elif has_reason:
        action = "analyze_reason"
    elif has_process:
        action = "ask_process"
    elif has_ranking:
        action = "query_ranking"
    elif metric is not None:
        action = "query_metric"
    else:
        action = "clarify"

    if action in {"ask_definition", "ask_process"}:
        needs_docs = True
        needs_data = bool(metric and has_explicit_data_scope and time_range)
    elif action == "analyze_reason":
        needs_data = bool(metric or time_range or category)
        needs_docs = True
    elif action in {"query_metric", "query_ranking"}:
        needs_data = True
        needs_docs = has_doc_term
    else:
        needs_data = False
        needs_docs = has_doc_term

    comparison = None
    if any(term in text for term in ("环比", "上月", "和上个月", "对比上月")):
        comparison = "month_over_month"
    elif any(term in text for term in ("同比", "去年同期", "和去年")):
        comparison = "year_over_year"
    elif action == "analyze_reason" and time_range:
        comparison = "month_over_month"

    missing_fields: list[str] = []
    if action == "clarify" and not needs_docs:
        missing_fields.append("analysis_goal")
    bare_metric_questions = {
        "退款率", "退货率", "退款数", "订单数", "工单数", "退款金额", "评分",
    }
    if normalized in bare_metric_questions:
        missing_fields.extend(["time_range", "category"])

    if action == "clarify":
        confidence = 0.45
    elif missing_fields:
        confidence = 0.78
    elif metric and (time_range or category):
        confidence = 0.98
    elif action in {"ask_definition", "ask_process"}:
        confidence = 0.95
    elif action == "analyze_reason" and needs_data:
        confidence = 0.94
    else:
        confidence = 0.88

    reason = (
        f"识别动作={action}, 指标={metric or '未指定'}, "
        f"数据需求={'是' if needs_data else '否'}, 文档需求={'是' if needs_docs else '否'}。"
    )
    return IntentSlots(
        action=action,
        metric=metric,
        time_range=time_range,
        category=category,
        comparison=comparison,
        needs_data=needs_data,
        needs_docs=needs_docs,
        missing_fields=list(dict.fromkeys(missing_fields)),
        confidence=confidence,
        reason=reason,
    )
