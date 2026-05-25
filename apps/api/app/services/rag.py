"""
RAG 检索增强生成 — 混合检索 + RRF 融合 + LLM Rerank。

Pipeline:
  Switches:
    RAG_ENABLE_MQE / RAG_ENABLE_BM25 / RAG_ENABLE_RRF /
    RAG_ENABLE_RERANK / RAG_ENABLE_ADJACENT_CONTEXT.
  1. MQE 多查询扩展 → LLM 生成 3 个语义变体
  2. Dense 检索 → Chroma 向量检索 (BGE-M3)
  3. Sparse 检索 → BM25 关键词检索
  4. RRF 融合 → Reciprocal Rank Fusion (k=60)
  5. 合并且去重 → 按 chunk_id 去重
  6. LLM Rerank → 对主命中候选集重排序，取 top-k
  7. 相邻 chunk 扩展 → 对 top-k 主命中拉取前后相邻片段，只补上下文，不参与排序
  8. 格式化 → 输出 Citation 列表
"""

import math
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.chat import Citation
from app.services.chroma_store import query_chroma
from app.services.chunking import TextChunk, load_document_chunks

RagSwitches = dict[str, bool]

RAG_PROFILE_SWITCHES: dict[str, RagSwitches] = {
    "dense": {
        "mqe": False,
        "bm25": False,
        "rrf": False,
        "rerank": False,
        "adjacent_context": False,
    },
    "dense-neighbor": {
        "mqe": False,
        "bm25": False,
        "rrf": False,
        "rerank": False,
        "adjacent_context": True,
    },
    "hybrid": {
        "mqe": False,
        "bm25": True,
        "rrf": True,
        "rerank": False,
        "adjacent_context": False,
    },
    "hybrid-neighbor": {
        "mqe": False,
        "bm25": True,
        "rrf": True,
        "rerank": False,
        "adjacent_context": True,
    },
    "mqe-hybrid-neighbor": {
        "mqe": True,
        "bm25": True,
        "rrf": True,
        "rerank": False,
        "adjacent_context": True,
    },
}


def _settings_switches() -> RagSwitches:
    return {
        "mqe": settings.rag_enable_mqe,
        "bm25": settings.rag_enable_bm25,
        "rrf": settings.rag_enable_rrf,
        "rerank": settings.rag_enable_rerank,
        "adjacent_context": settings.rag_enable_adjacent_context,
    }


def select_rag_profile(query: str) -> tuple[str, RagSwitches, str]:
    """规则型 RAG Router：默认走 Dense，只把少数复杂问题交给增强链路。"""
    text = query.lower()

    simple_patterns = [
        "是什么", "有哪些", "多少", "口径", "定义", "流程", "规则", "要求",
        "what is", "list", "explain",
    ]

    keyword_terms = [
        "p1", "p2", "fcr", "sla", "sku", "sop",
    ]

    domain_terms = [
        "会员", "促销", "物流", "风控", "退款", "退货", "换货", "投诉", "质量",
        "品控", "供应商", "客服", "话术", "指标", "诊断", "审核",
    ]

    complex_terms = [
        "为什么", "原因", "归因", "诊断", "结合", "同时", "冲突", "优先级",
        "对比", "差异", "影响", "应该先", "如何判断", "如何回退",
    ]

    strong_multi_doc_terms = [
        "同时", "冲突", "优先级", "结合", "归因", "诊断", "如何判断", "应该先",
    ]

    domain_hits = sum(1 for term in domain_terms if term in text)
    has_keyword = any(term in text for term in keyword_terms)
    has_complex_intent = any(term in text for term in complex_terms)
    has_strong_multi_doc_intent = any(term in text for term in strong_multi_doc_terms)
    is_simple = any(pattern in text for pattern in simple_patterns)

    # 1. 简单事实类优先保护：即使命中“规则/流程”，也先走 Dense
    if is_simple and not has_strong_multi_doc_intent:
        return (
            "dense-neighbor",
            RAG_PROFILE_SWITCHES["dense-neighbor"],
            "简单事实/定义类问题，优先使用 Dense 快路径",
        )

    # 2. 只有强多文档意图 + 至少 3 个业务域，才启用 MQE
    if has_strong_multi_doc_intent and domain_hits >= 3:
        return (
            "mqe-hybrid-neighbor",
            RAG_PROFILE_SWITCHES["mqe-hybrid-neighbor"],
            "强多文档综合问题，启用 MQE + Hybrid",
        )

    # 3. 术语类问题不再默认 hybrid，除非同时有复杂意图
    if has_keyword and has_complex_intent and domain_hits >= 2:
        return (
            "hybrid-neighbor",
            RAG_PROFILE_SWITCHES["hybrid-neighbor"],
            "术语 + 复杂意图问题，启用 Hybrid 作为关键词补充",
        )

    # 4. 其他全部走 Dense
    return (
        "dense-neighbor",
        RAG_PROFILE_SWITCHES["dense-neighbor"],
        "默认使用 Dense 快路径，避免复杂链路带来排序噪声",
    )


# ── Tokenizer ────────────────────────────────────────────────────────

def tokenize(text: str) -> set[str]:
    terms = set(re.findall(r"[a-zA-Z0-9]+|[一-鿿]{2,}", text.lower()))
    domain_terms = [
        "退款", "售后", "尺码", "色差", "退款率", "工单", "指标",
        "政策", "sop", "服装", "鞋靴", "面料",
    ]
    for term in domain_terms:
        if term in text.lower():
            terms.add(term)
    return terms


def _tokenize_for_bm25(text: str) -> list[str]:
    """BM25 用：返回词条列表（非 set），保留词频信息。"""
    tokens = re.findall(r"[a-zA-Z0-9]+|[一-鿿]{2,}", text.lower())
    domain_terms = [
        "退款", "售后", "尺码", "色差", "退款率", "工单", "指标",
        "政策", "sop", "服装", "鞋靴", "面料", "会员", "物流",
        "差评", "退货", "换货", "品控",
    ]
    for term in domain_terms:
        if term in text.lower():
            tokens.append(term)
    return tokens


# ── BM25 稀疏检索 ────────────────────────────────────────────────────

class BM25Retriever:
    """
    轻量 BM25 实现，无需外部依赖。支持索引持久化。

    BM25(D, Q) = Σ IDF(qi) * f(qi,D) * (k1+1) / (f(qi,D) + k1 * (1-b + b*|D|/avgdl))
    默认 k1=1.5, b=0.75
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict[str, Any]] = []
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0
        self._built = False

    # ── 构建 ────────────────────────────────────────────────────────

    def build(self, chunks: list[TextChunk]) -> None:
        """从 chunk 列表构建 BM25 索引。"""
        self._docs = [
            {
                "id": chunk.id,
                "tokens": _tokenize_for_bm25(chunk.text),
                "text": chunk.text,
                "metadata": dict(chunk.metadata),
            }
            for chunk in chunks
        ]
        N = len(self._docs)
        if N == 0:
            self._built = True
            return

        df: dict[str, int] = defaultdict(int)
        doc_lengths: list[int] = []
        for doc in self._docs:
            unique_tokens = set(doc["tokens"])
            for token in unique_tokens:
                df[token] += 1
            doc_lengths.append(len(doc["tokens"]))

        self._avgdl = sum(doc_lengths) / N

        for token, freq in df.items():
            self._idf[token] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)

        self._built = True

    # ── 持久化 ──────────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """序列化索引到磁盘（pickle）。"""
        import pickle

        data = {
            "k1": self.k1,
            "b": self.b,
            "docs": self._docs,
            "idf": self._idf,
            "avgdl": self._avgdl,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self, path: Path) -> bool:
        """从磁盘反序列化索引。返回是否加载成功。"""
        import pickle

        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.k1 = data["k1"]
            self.b = data["b"]
            self._docs = data["docs"]
            self._idf = data["idf"]
            self._avgdl = data["avgdl"]
            self._built = True
            return True
        except Exception:
            return False

    # ── 检索 ────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """BM25 搜索，返回 records 列表。"""
        if not self._built or not self._docs:
            return []

        query_tokens = _tokenize_for_bm25(query)
        if not query_tokens:
            return []

        # 查询词频
        qf: dict[str, int] = defaultdict(int)
        for token in query_tokens:
            qf[token] += 1

        scores: list[tuple[float, int]] = []
        for idx, doc in enumerate(self._docs):
            doc_tokens = doc["tokens"]
            doc_len = len(doc_tokens)
            if doc_len == 0:
                continue

            tf: dict[str, int] = defaultdict(int)
            for token in doc_tokens:
                tf[token] += 1

            score = 0.0
            for token, query_tf in qf.items():
                if token not in tf:
                    continue
                idf = self._idf.get(token, 0)
                term_freq = tf[token]
                numerator = term_freq * (self.k1 + 1)
                denominator = term_freq + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl)
                score += idf * numerator / denominator * query_tf

            if score > 0:
                scores.append((score, idx))

        scores.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        for score, idx in scores[:top_k]:
            doc = self._docs[idx]
            results.append({
                "id": doc["id"],
                "document": doc["text"],
                "metadata": doc["metadata"],
                "score": round(score, 4),
                "source": "bm25",
            })
        return results


# ── RRF 融合 ─────────────────────────────────────────────────────────

def _rrf_fuse(
    dense_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion：融合 Dense 和 Sparse 两路排名。

    公式: RRFscore(d) = Σ 1/(k + rank_i(d))
    k=60 是学术界和实践的默认值。

    同时合并两路的 source、rank、matched_queries 信息。
    """
    rrf_scores: dict[str, float] = {}
    docs: dict[str, dict[str, Any]] = {}

    for rank, rec in enumerate(dense_results, start=1):
        cid = str(rec["id"])
        qw = rec.get("query_weight", 1.0)  # 变体权重：原始 1.0，扩展递减
        rrf_scores[cid] = rrf_scores.get(cid, 0) + qw / (k + rank)
        if cid not in docs:
            docs[cid] = dict(rec)
            docs[cid]["dense_rank"] = rank
            docs[cid]["sparse_rank"] = None
            docs[cid]["retrieval_sources"] = ["dense"]
            docs[cid]["matched_queries"] = list(rec.get("matched_queries", []))
        else:
            docs[cid]["dense_rank"] = rank
            docs[cid]["retrieval_sources"] = sorted(
                set(docs[cid].get("retrieval_sources", []) + ["dense"])
            )
            docs[cid]["matched_queries"] = list(
                dict.fromkeys(docs[cid].get("matched_queries", []) + rec.get("matched_queries", []))
            )

    for rank, rec in enumerate(sparse_results, start=1):
        cid = str(rec["id"])
        qw = rec.get("query_weight", 1.0)
        rrf_scores[cid] = rrf_scores.get(cid, 0) + qw / (k + rank)
        if cid not in docs:
            docs[cid] = dict(rec)
            docs[cid]["dense_rank"] = None
            docs[cid]["sparse_rank"] = rank
            docs[cid]["retrieval_sources"] = ["bm25"]
            docs[cid]["matched_queries"] = list(rec.get("matched_queries", []))
        else:
            docs[cid]["sparse_rank"] = rank
            docs[cid]["retrieval_sources"] = sorted(
                set(docs[cid].get("retrieval_sources", []) + ["bm25"])
            )
            docs[cid]["matched_queries"] = list(
                dict.fromkeys(docs[cid].get("matched_queries", []) + rec.get("matched_queries", []))
            )

    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    results: list[dict[str, Any]] = []
    for cid, rrf_score in fused:
        doc = docs[cid]
        doc["rrf_score"] = round(rrf_score, 4)
        doc["score"] = round(rrf_score * 100, 3)
        doc.setdefault("dense_rank", None)
        doc.setdefault("sparse_rank", None)
        doc.setdefault("retrieval_sources", [])
        doc.setdefault("matched_queries", [])

        # source 保留原始的 dense/bm25/both 标记
        sources = doc["retrieval_sources"]
        doc["source"] = "both" if len(sources) >= 2 else (sources[0] if sources else "unknown")
        results.append(doc)

    return results


# ── BM25 单例 + 索引持久化 ──────────────────────────────────────────

_bm25: BM25Retriever | None = None


def _compute_docs_fingerprint() -> str:
    """对文档目录内容做指纹（文件名 + 大小 + 修改时间），用于检测变更。"""
    import hashlib

    documents_dir = settings.resolve_api_path(settings.documents_dir)
    hasher = hashlib.sha256()
    if not documents_dir.exists():
        return "empty"
    for path in sorted(documents_dir.glob("*.md")):
        stat = path.stat()
        hasher.update(f"{path.name}:{stat.st_size}:{stat.st_mtime}".encode())
    return hasher.hexdigest()[:16]


def _get_bm25_cache_path() -> Path:
    """BM25 索引缓存文件路径。"""
    cache_dir = settings.resolve_api_path("../../data")
    return cache_dir / "bm25_index.pkl"


def _get_bm25() -> BM25Retriever:
    """获取 BM25 实例：缓存命中则反序列化，否则构建并保存。"""
    global _bm25
    if _bm25 is not None:
        return _bm25

    _bm25 = BM25Retriever()
    cache_path = _get_bm25_cache_path()

    # 检查缓存是否有效
    fingerprint = _compute_docs_fingerprint()
    fingerprint_path = _get_bm25_cache_path().with_suffix(".fingerprint")

    cache_valid = False
    if cache_path.exists() and fingerprint_path.exists():
        try:
            cached_fp = fingerprint_path.read_text().strip()
            if cached_fp == fingerprint:
                cache_valid = _bm25.load(cache_path)
        except Exception:
            pass

    if not cache_valid:
        # 重建索引
        documents_dir = settings.resolve_api_path(settings.documents_dir)
        chunks = load_document_chunks(
            documents_dir=documents_dir,
            strategy=settings.chunk_strategy,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        _bm25.build(chunks)
        # 持久化
        try:
            _bm25.save(cache_path)
            fingerprint_path.write_text(fingerprint)
        except Exception:
            pass  # 写入失败不影响使用

    return _bm25


# ── MQE 多查询扩展 ───────────────────────────────────────────────────

_MQE_PROMPT = """你是一个搜索查询优化器。将用户问题扩展为 3 个语义不同但目标一致的检索查询。

要求：
- 每个查询一行，不要编号，不要前缀
- 用不同的措辞和角度表达同一信息需求
- 包含原始问题中的关键实体（类目、时间、指标名等）
- 全部使用中文

用户问题：{question}

输出 3 行："""


def _mqe_expand_llm(question: str) -> list[str]:
    """调用 LLM 生成多个查询变体。失败时回退到规则扩展。"""
    if not settings.siliconflow_api_key:
        return _mqe_expand_rules(question)

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "user", "content": _MQE_PROMPT.format(question=question)},
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }

    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=20.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        variants: list[str] = []
        for line in content.split("\n"):
            cleaned = re.sub(r"^[\d\.\)\-\s]+", "", line).strip()
            if cleaned and len(cleaned) >= 4:
                variants.append(cleaned)
            if len(variants) >= 3:
                break

        if len(variants) >= 2:
            return [question] + variants[:3]

    except Exception:
        pass

    return _mqe_expand_rules(question)


def _mqe_expand_rules(question: str) -> list[str]:
    """规则回退：基于关键词构造变体查询。"""
    variants = [question]
    if "退款率" in question or "退款" in question:
        variants.append(f"退款率 指标 口径 售后原因 {question}")
    if "工单" in question or "客服" in question:
        variants.append(f"客服工单 分类标准 售后处理 SOP {question}")
    if "政策" in question or "规则" in question:
        variants.append(f"售后政策 退款规则 会员权益 {question}")
    if "为什么" in question or "原因" in question:
        variants.append(f"数据异常原因 售后政策 指标波动 {question}")
    return list(dict.fromkeys(variants))[:4]


# ── 相邻 Chunk 扩展 ──────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_chunk_index() -> dict[str, dict[str, Any]]:
    """加载所有文档 chunk 的索引（按 chunk_id 查找）。"""
    documents_dir = settings.resolve_api_path(settings.documents_dir)
    chunks = load_document_chunks(
        documents_dir=documents_dir,
        strategy=settings.chunk_strategy,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    return {
        chunk.id: {
            "text": chunk.text,
            "metadata": dict(chunk.metadata),
        }
        for chunk in chunks
    }


def _expand_adjacent_chunks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对每个命中 chunk 拉取前后相邻片段，并追加到排序结果之后。"""
    index = _load_chunk_index()
    seen: set[str] = set()
    primary_records: list[dict[str, Any]] = []
    neighbor_records: list[dict[str, Any]] = []

    for rec in records:
        chunk_id = str(rec["id"])
        if chunk_id not in seen:
            seen.add(chunk_id)
            primary_records.append(rec)

        meta = rec.get("metadata", {})
        doc_id = str(meta.get("doc_id", ""))
        chunk_idx = int(meta.get("chunk_index", -1))
        if chunk_idx < 0:
            continue

        for offset, score_penalty in [(-1, 0.85), (1, 0.80)]:
            neighbor_id = f"{doc_id}-{chunk_idx + offset}"
            if neighbor_id in seen:
                continue
            neighbor = index.get(neighbor_id)
            if neighbor is None:
                continue
            seen.add(neighbor_id)
            neighbor_records.append({
                "id": neighbor_id,
                "document": neighbor["text"],
                "metadata": neighbor["metadata"],
                "score": round(rec["score"] * score_penalty, 3),
                "source_hit": chunk_id,       # 指向主命中 chunk
                "is_neighbor": True,           # 标记为相邻扩展
                "retrieval_sources": [],
                "matched_queries": [],
                "dense_rank": None,
                "sparse_rank": None,
                "rrf_score": None,
                "rerank_score": None,
            })

    return primary_records + neighbor_records


# ── LLM Rerank ───────────────────────────────────────────────────────

_RERANK_PROMPT = """你是一个搜索相关性评估器。根据用户问题，对以下检索结果片段逐一评分。

评分标准（1-10）：
- 10：完全匹配，直接回答问题
- 7-9：高度相关，包含关键信息
- 4-6：部分相关，有参考价值
- 1-3：基本无关

用户问题：{question}

检索结果：
{passages}

请严格按以下格式输出（每行一个分数，不要其他内容）：
<chunk_id> <分数>
"""


def _llm_rerank(
    question: str, records: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    """用 LLM 对候选集重排序。"""
    if len(records) <= top_k:
        return records
    if not settings.siliconflow_api_key:
        return records[:top_k]

    candidates = records[: max(top_k * 3, 10)]
    passages_lines: list[str] = []
    for rec in candidates:
        snippet = rec["document"].strip()[:300].replace("\n", " ")
        passages_lines.append(f"<{rec['id']}> {snippet}")

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "user",
                "content": _RERANK_PROMPT.format(
                    question=question, passages="\n\n".join(passages_lines)
                ),
            },
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }

    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return records[:top_k]

    # 解析 LLM 返回的分数
    scores: dict[str, float] = {}
    for line in content.split("\n"):
        line = line.strip()
        match = re.match(r"<?([\w\-\.]+)>?\s+([\d\.]+)", line)
        if match:
            chunk_id = match.group(1)
            try:
                score = float(match.group(2))
                scores[chunk_id] = min(max(score, 1), 10)
            except ValueError:
                continue

    if not scores:
        return records[:top_k]

    # 加权合并：LLM 分数 × 0.6 + 原始向量分数 × 0.4
    for rec in candidates:
        cid = str(rec["id"])
        if cid in scores:
            rec["rerank_score"] = scores[cid]
            rec["final_score"] = round(scores[cid] * 0.6 + rec["score"] * 10 * 0.4, 2)

    candidates.sort(key=lambda r: r.get("final_score", r["score"]), reverse=True)
    return candidates[:top_k]


# ── 检索主流程 ───────────────────────────────────────────────────────


def retrieve_docs(query: str, top_k: int | None = None) -> list[Citation]:
    """主入口：RAG 检索 + MQE + 相邻扩展 + LLM Rerank。"""
    k = top_k or settings.top_k
    from app.services.rag_graph import run_rag_retrieval_graph


    return run_rag_retrieval_graph(query, k)


def _retrieve_with_optimizations(
    query: str,
    top_k: int,
    switches: RagSwitches | None = None,
    profile: str = "manual",
    route_reason: str = "use switches from settings",
) -> list[Citation]:
    """完整优化管道：MQE → Dense+Sparse → RRF → 去重 → 相邻扩展 → LLM Rerank。"""
    # 1. MQE 多查询扩展
    active = switches or _settings_switches()
    variants = _mqe_expand_llm(query) if active["mqe"] else [query]

    # 2. Dense + Sparse 并行检索
    dense_records: list[dict[str, Any]] = []
    sparse_records: list[dict[str, Any]] = []
    dense_seen: set[str] = set()
    sparse_seen: set[str] = set()

    bm25 = _get_bm25() if active["bm25"] else None

    # 变体权重：原始 = 1.0，扩展递减
    variant_weights = [1.0, 0.7, 0.5, 0.3]

    for i, variant in enumerate(variants):
        weight = variant_weights[i] if i < len(variant_weights) else 0.3
        # Dense: Chroma 向量检索
        for rank, rec in enumerate(query_chroma(variant, top_k=8), start=1):
            rid = str(rec["id"])
            matched = rec.setdefault("matched_queries", [])
            if variant not in matched:
                matched.append(variant)
            rec.setdefault("query_weight", 0)
            rec["query_weight"] = max(rec["query_weight"], weight)
            if rid not in dense_seen:
                dense_seen.add(rid)
                rec["source"] = "dense"
                rec["is_neighbor"] = False
                rec["dense_rank"] = rank
                rec["sparse_rank"] = None
                rec["retrieval_sources"] = ["dense"]
                rec["rrf_score"] = None
                dense_records.append(rec)
        # Sparse: BM25 关键词检索
        if bm25 is not None:
            for rank, rec in enumerate(bm25.search(variant, top_k=8), start=1):
                rid = str(rec["id"])
                matched = rec.setdefault("matched_queries", [])
                if variant not in matched:
                    matched.append(variant)
                rec.setdefault("query_weight", 0)
                rec["query_weight"] = max(rec["query_weight"], weight)
                if rid not in sparse_seen:
                    sparse_seen.add(rid)
                    rec["is_neighbor"] = False
                    rec["dense_rank"] = None
                    rec["sparse_rank"] = rank
                    rec["retrieval_sources"] = ["bm25"]
                    rec["rrf_score"] = None
                    sparse_records.append(rec)

    if not dense_records and not sparse_records:
        return []

    # 3. RRF 融合 Dense + Sparse 排名
    if active["bm25"] and active["rrf"] and sparse_records:
        all_records = _rrf_fuse(dense_records, sparse_records)
    else:
        all_records = sorted(dense_records, key=lambda r: r.get("score", 0), reverse=True)

    # 4. 去重（RRF 已做，这里保险）
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for rec in all_records:
        rid = str(rec["id"])
        if rid not in seen:
            seen.add(rid)
            deduped.append(rec)
    all_records = deduped

    # 5. LLM Rerank 精排
    if active["rerank"]:
        all_records = _llm_rerank(query, all_records, top_k)
    else:
        all_records = all_records[:top_k]

    # 6. 相邻 chunk 扩展：排序完成后再追加，只作为上下文补充
    if active["adjacent_context"]:
        all_records = _expand_adjacent_chunks(all_records)

    # 7. 格式化为 Citation — 保留全链路检索元数据
    citations: list[Citation] = []
    for rec in all_records:
        metadata = rec.get("metadata", {})
        citations.append(
            Citation(
                doc_id=str(metadata.get("doc_id", "unknown")),
                title=str(metadata.get("title", "未知文档")),
                chunk_id=str(rec["id"]),
                snippet=re.sub(r"\s+", " ", str(rec["document"])).strip()[:260],
                score=round(rec.get("final_score", rec["score"]), 3),
                # ── 检索溯源 ──
                retrieval_sources=rec.get("retrieval_sources", []),
                dense_rank=rec.get("dense_rank"),
                sparse_rank=rec.get("sparse_rank"),
                rrf_score=rec.get("rrf_score"),
                rerank_score=rec.get("rerank_score"),
                matched_queries=rec.get("matched_queries", []),
                # ── 上下文扩展 ──
                is_neighbor=rec.get("is_neighbor", False),
                source_hit=rec.get("source_hit"),
                rag_profile=profile,
                router_reason=route_reason,
            )
        )
    return citations


# ── 本地关键词检索（回退路径，同样享受 MQE 和相邻扩展）─────────────

def _retrieve_from_local_docs(
    query: str,
    top_k: int,
    switches: RagSwitches | None = None,
    profile: str = "manual",
    route_reason: str = "use switches from settings",
) -> list[Citation]:
    """本地回退检索：使用 BM25 + 相邻扩展。"""
    active = switches or _settings_switches()
    bm25 = _get_bm25()
    variants = _mqe_expand_llm(query) if active["mqe"] else [query]

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        for rec in bm25.search(variant, top_k=top_k):
            rid = str(rec["id"])
            if rid not in seen:
                seen.add(rid)
                all_records.append(rec)

    if all_records and active["adjacent_context"]:
        all_records = _expand_adjacent_chunks(all_records[:top_k])
    else:
        all_records = all_records[:top_k]

    citations: list[Citation] = []
    for rec in all_records:
        metadata = rec.get("metadata", {})
        citations.append(
            Citation(
                doc_id=str(metadata.get("doc_id", "unknown")),
                title=str(metadata.get("title", "未知文档")),
                chunk_id=str(rec["id"]),
                snippet=re.sub(r"\s+", " ", str(rec["document"])).strip()[:260],
                score=round(rec.get("score", 0), 3),
                rag_profile=profile,
                router_reason=route_reason,
            )
        )
    return citations



# ── 旧接口兼容 ───────────────────────────────────────────────────────

def query_rewrite(query: str) -> list[str]:
    """旧接口兼容：返回 MQE 扩展结果。"""
    return _mqe_expand_llm(query)
