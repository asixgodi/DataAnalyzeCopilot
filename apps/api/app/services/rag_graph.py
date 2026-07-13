import json
import re
from functools import lru_cache
from typing import Any, Literal

import httpx
from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.schemas.chat import Citation
from app.services.rag import (
    RAG_PROFILE_SWITCHES,
    RagSwitches,
    _retrieve_from_local_docs,
    _retrieve_with_optimizations,
    _settings_switches,
    select_rag_profile,
)

# LangSmith traceable — 仅在包已安装时启用
try:
    from langsmith import traceable as _ls_traceable
except ImportError:  # pragma: no cover
    def _ls_traceable(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        def _wrap(fn):  # type: ignore[no-untyped-def]
            return fn
        return _wrap


RagRoute = Literal["manual", "dense", "hybrid", "deep"]
LLM_ROUTER_PROFILES = {"dense-neighbor", "hybrid-neighbor", "mqe-hybrid-neighbor"}


_LLM_ROUTER_PROMPT = """你是 RAG 检索路由器。你的任务不是回答问题，而是选择最低成本且最可能稳定命中的检索链路。

可选链路：
1. dense-neighbor
适合定义、口径、流程、单一政策、单一文档解释、术语解释、一般售后问题。这是默认选项。

2. mqe-hybrid-neighbor
只适合明确需要跨多个规则文档综合判断的问题，例如同时涉及会员、促销、物流、风控、退款、投诉、质量中的至少 3 类，并且问题要求处理冲突、优先级、归因或综合决策。

3. hybrid-neighbor
只适合明确需要关键词精确召回的问题，例如用户问题包含 P1、P2、FCR、SLA、SKU、SOP、RRF、BM25、MQE、HNSW 等明确术语或编号，并且 Dense 可能遗漏这些精确词。不要把普通政策解释、流程解释、原因分析路由到 hybrid-neighbor。

选择原则：
- 默认选择 dense-neighbor。
- 不要因为出现 FCR、SLA、SKU、SOP 就选择复杂链路。
- 不要因为问题包含“原因/流程/规则”就选择复杂链路。
- 只有明确需要关键词精确召回时，才选择 hybrid-neighbor。
- 只有当单一路径明显不够，需要跨多个规则文档综合判断时，才选择 mqe-hybrid-neighbor。
- 如果不确定，选择 dense-neighbor。

用户问题：
{query}

只输出 JSON，不要输出解释性前后缀：
{{
  "profile": "dense-neighbor 或 hybrid-neighbor 或 mqe-hybrid-neighbor",
  "reason": "一句中文理由",
  "confidence": 0到1之间的小数
}}
"""


def _update(state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    next_state = dict(state)
    next_state.update(kwargs)
    return next_state


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM router returned no JSON object")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM router JSON must be an object")
    return payload


@_ls_traceable(name="RAG LLM Router", tags=["rag", "router", "llm"])
def _llm_route_query(query: str) -> tuple[str, RagSwitches, str, float]:
    if not settings.siliconflow_api_key:
        raise RuntimeError("SILICONFLOW_API_KEY is required for LLM router")

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "user",
                "content": _LLM_ROUTER_PROMPT.format(query=query),
            }
        ],
        "temperature": 0,
        "max_tokens": 300,
    }

    with httpx.Client() as client:
        resp = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=20.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

    data = _extract_json_object(content)
    profile = str(data.get("profile", "")).strip()
    reason = str(data.get("reason", "")).strip() or "LLM Router selected retrieval profile"
    confidence = float(data.get("confidence", 0))

    if profile not in LLM_ROUTER_PROFILES:
        raise ValueError(f"Unsupported LLM router profile: {profile}")
    if confidence < settings.rag_router_confidence_threshold:
        raise ValueError(f"LLM router confidence too low: {confidence}")

    return profile, RAG_PROFILE_SWITCHES[profile], f"LLM Router: {reason}", confidence


def _rule_route_query(query: str) -> tuple[str, RagSwitches, str, float]:
    profile, switches, reason = select_rag_profile(query)
    return profile, switches, f"Rule Router: {reason}", 1.0


def _route_query_node(state: dict[str, Any]) -> dict[str, Any]:
    query = state["query"]
    if not settings.rag_enable_router:
        return _update(
            state,
            profile="manual",
            switches=_settings_switches(),
            route_reason="RAG Router disabled; use switches from settings",
        )

    if settings.rag_router_mode.lower() == "llm":
        try:
            profile, switches, reason, confidence = _llm_route_query(query)
            return _update(
                state,
                profile=profile,
                switches=switches,
                route_reason=reason,
                router_confidence=confidence,
                router_mode="llm",
            )
        except Exception as exc:
            profile, switches, reason, confidence = _rule_route_query(query)
            return _update(
                state,
                profile=profile,
                switches=switches,
                route_reason=f"{reason}; LLM Router fallback: {exc}",
                router_confidence=confidence,
                router_mode="rule_fallback",
            )

    profile, switches, reason, confidence = _rule_route_query(query)
    return _update(
        state,
        profile=profile,
        switches=switches,
        route_reason=reason,
        router_confidence=confidence,
        router_mode="rule",
    )


def _route_condition(state: dict[str, Any]) -> RagRoute:
    profile = state.get("profile", "manual")
    if profile == "manual":
        return "manual"
    if profile.startswith("mqe-"):
        return "deep"
    if profile.startswith("hybrid"):
        return "hybrid"
    return "dense"


def _retrieve_with_profile(
    state: dict[str, Any],
    profile: str,
    switches: RagSwitches,
) -> dict[str, Any]:
    query = state["query"]
    top_k = int(state["top_k"])
    route_reason = state.get("route_reason", "")

    if settings.vector_store == "chroma":
        try:
            citations = _retrieve_with_optimizations(
                query,
                top_k,
                switches=switches,
                profile=profile,
                route_reason=route_reason,
            )
        except Exception:
            citations = _retrieve_from_local_docs(
                query,
                top_k,
                switches=switches,
                profile=profile,
                route_reason=route_reason,
            )
    else:
        citations = _retrieve_from_local_docs(
            query,
            top_k,
            switches=switches,
            profile=profile,
            route_reason=route_reason,
        )

    return _update(state, citations=citations)


def _retrieve_manual_node(state: dict[str, Any]) -> dict[str, Any]:
    return _retrieve_with_profile(
        state,
        "manual",
        state.get("switches") or _settings_switches(),
    )


def _retrieve_dense_node(state: dict[str, Any]) -> dict[str, Any]:
    return _retrieve_with_profile(
        state,
        state.get("profile", "dense-neighbor"),
        state.get("switches") or RAG_PROFILE_SWITCHES["dense-neighbor"],
    )


def _retrieve_hybrid_node(state: dict[str, Any]) -> dict[str, Any]:
    return _retrieve_with_profile(
        state,
        state.get("profile", "hybrid-neighbor"),
        state.get("switches") or RAG_PROFILE_SWITCHES["hybrid-neighbor"],
    )


def _retrieve_deep_node(state: dict[str, Any]) -> dict[str, Any]:
    return _retrieve_with_profile(
        state,
        state.get("profile", "mqe-hybrid-neighbor"),
        state.get("switches") or RAG_PROFILE_SWITCHES["mqe-hybrid-neighbor"],
    )


def _finish_node(state: dict[str, Any]) -> dict[str, Any]:
    return _update(
        state,
        trace=[
            {
                "node": "route_query",
                "profile": state.get("profile"),
                "reason": state.get("route_reason"),
                "mode": state.get("router_mode"),
                "confidence": state.get("router_confidence"),
            },
            {
                "node": "retrieve",
                "citation_count": len(state.get("citations", [])),
            },
        ],
    )


@lru_cache(maxsize=1)
def build_rag_graph():
    workflow = StateGraph(dict)
    workflow.add_node("route_query", _route_query_node)
    workflow.add_node("retrieve_manual", _retrieve_manual_node)
    workflow.add_node("retrieve_dense", _retrieve_dense_node)
    workflow.add_node("retrieve_hybrid", _retrieve_hybrid_node)
    workflow.add_node("retrieve_deep", _retrieve_deep_node)
    workflow.add_node("finish", _finish_node)

    workflow.set_entry_point("route_query")
    workflow.add_conditional_edges(
        "route_query",
        _route_condition,
        {
            "manual": "retrieve_manual",
            "dense": "retrieve_dense",
            "hybrid": "retrieve_hybrid",
            "deep": "retrieve_deep",
        },
    )
    workflow.add_edge("retrieve_manual", "finish")
    workflow.add_edge("retrieve_dense", "finish")
    workflow.add_edge("retrieve_hybrid", "finish")
    workflow.add_edge("retrieve_deep", "finish")
    workflow.add_edge("finish", END)
    return workflow.compile()


def run_rag_retrieval_graph(query: str, top_k: int) -> list[Citation]:
    graph = build_rag_graph()
    result = graph.invoke(
        {
            "query": query,
            "top_k": top_k,
            "profile": "",
            "switches": {},
            "route_reason": "",
            "citations": [],
            "trace": [],
            "router_mode": "",
            "router_confidence": 0,
        }
    )
    return result.get("citations", [])
