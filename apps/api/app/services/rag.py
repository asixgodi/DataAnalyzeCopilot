"""
RAG 检索增强生成 — 混合检索 + RRF 融合 + LLM Rerank。

Pipeline:
  1. MQE 多查询扩展 → LLM 生成 3 个语义变体
  2. Dense 检索 → Chroma 向量 (BGE-M3)
  3. Sparse 检索 → BM25 关键词
  4. RRF 融合 → Reciprocal Rank Fusion (k=60)
  5. 合并且去重 → 按 chunk_id 去重
  6. 相邻 chunk 扩展 → 拉取前后相邻片段
  7. LLM Rerank → 对候选集重排序，取 top-k
  8. 格式化 → 输出 Citation 列表
"""

import math
import re
from collections import defaultdict
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.chat import Citation
from app.services.chroma_store import query_chroma
from app.services.chunking import TextChunk, load_document_chunks


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
    轻量 BM25 实现，无需外部依赖。

    BM25(D, Q) = Σ IDF(qi) * f(qi,D) * (k1+1) / (f(qi,D) + k1 * (1-b + b*|D|/avgdl))
    默认 k1=1.5, b=0.75
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict[str, Any]] = []  # [{id, tokens, text, metadata}]
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0
        self._built = False

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

        # 文档频率
        df: dict[str, int] = defaultdict(int)
        doc_lengths: list[int] = []
        for doc in self._docs:
            unique_tokens = set(doc["tokens"])
            for token in unique_tokens:
                df[token] += 1
            doc_lengths.append(len(doc["tokens"]))

        self._avgdl = sum(doc_lengths) / N

        # IDF
        for token, freq in df.items():
            self._idf[token] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)

        self._built = True

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
    k=60 是学术界和实践的默认值（Cohere/Weaviate 均用此值）。
    """
    rrf_scores: dict[str, float] = {}
    docs: dict[str, dict[str, Any]] = {}

    for rank, rec in enumerate(dense_results, start=1):
        cid = str(rec["id"])
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (k + rank)
        docs[cid] = rec

    for rank, rec in enumerate(sparse_results, start=1):
        cid = str(rec["id"])
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (k + rank)
        if cid not in docs:
            docs[cid] = rec

    # 排序：RRF 分从高到低
    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    results: list[dict[str, Any]] = []
    for cid, rrf_score in fused:
        doc = docs[cid]
        doc["rrf_score"] = round(rrf_score, 4)
        doc["score"] = round(rrf_score * 100, 3)  # 统一到 0-100 量纲
        results.append(doc)

    return results


# ── BM25 单例 ────────────────────────────────────────────────────────

_bm25: BM25Retriever | None = None


def _get_bm25() -> BM25Retriever:
    global _bm25
    if _bm25 is None:
        documents_dir = settings.resolve_api_path(settings.documents_dir)
        chunks = load_document_chunks(
            documents_dir=documents_dir,
            strategy=settings.chunk_strategy,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        _bm25 = BM25Retriever()
        _bm25.build(chunks)
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
    """对每个命中 chunk，拉取前后相邻片段。"""
    index = _load_chunk_index()
    expanded: dict[str, dict[str, Any]] = {}

    for rec in records:
        chunk_id = str(rec["id"])
        if chunk_id not in expanded:
            expanded[chunk_id] = rec

        meta = rec.get("metadata", {})
        doc_id = str(meta.get("doc_id", ""))
        chunk_idx = int(meta.get("chunk_index", -1))
        if chunk_idx < 0:
            continue

        for offset, score_penalty in [(-1, 0.85), (1, 0.80)]:
            neighbor_id = f"{doc_id}-{chunk_idx + offset}"
            if neighbor_id in expanded:
                continue
            neighbor = index.get(neighbor_id)
            if neighbor is None:
                continue
            expanded[neighbor_id] = {
                "id": neighbor_id,
                "document": neighbor["text"],
                "metadata": neighbor["metadata"],
                "score": round(rec["score"] * score_penalty, 3),
                "source_hit": chunk_id,
            }

    return sorted(expanded.values(), key=lambda r: r["score"], reverse=True)


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

    if settings.vector_store == "chroma":
        try:
            return _retrieve_with_optimizations(query, k)
        except Exception:
            return _retrieve_from_local_docs(query, k)
    return _retrieve_from_local_docs(query, k)


def _retrieve_with_optimizations(query: str, top_k: int) -> list[Citation]:
    """完整优化管道：MQE → Dense+Sparse → RRF → 去重 → 相邻扩展 → LLM Rerank。"""
    # 1. MQE 多查询扩展
    variants = _mqe_expand_llm(query)

    # 2. Dense + Sparse 并行检索
    dense_records: list[dict[str, Any]] = []
    sparse_records: list[dict[str, Any]] = []
    dense_seen: set[str] = set()
    sparse_seen: set[str] = set()

    bm25 = _get_bm25()

    for variant in variants:
        # Dense: Chroma 向量检索
        for rec in query_chroma(variant, top_k=8):
            rid = str(rec["id"])
            if rid not in dense_seen:
                dense_seen.add(rid)
                rec["source"] = "dense"
                dense_records.append(rec)
        # Sparse: BM25 关键词检索
        for rec in bm25.search(variant, top_k=8):
            rid = str(rec["id"])
            if rid not in sparse_seen:
                sparse_seen.add(rid)
                sparse_records.append(rec)

    if not dense_records and not sparse_records:
        return []

    # 3. RRF 融合 Dense + Sparse 排名
    all_records = _rrf_fuse(dense_records, sparse_records)

    # 4. 去重（RRF 已做，这里保险）
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for rec in all_records:
        rid = str(rec["id"])
        if rid not in seen:
            seen.add(rid)
            deduped.append(rec)
    all_records = deduped

    # 5. 相邻 chunk 扩展
    all_records = _expand_adjacent_chunks(all_records)

    # 6. LLM Rerank 精排
    all_records = _llm_rerank(query, all_records, top_k)

    # 7. 格式化为 Citation
    citations: list[Citation] = []
    for rec in all_records[:top_k]:
        metadata = rec.get("metadata", {})
        citations.append(
            Citation(
                doc_id=str(metadata.get("doc_id", "unknown")),
                title=str(metadata.get("title", "未知文档")),
                chunk_id=str(rec["id"]),
                snippet=re.sub(r"\s+", " ", str(rec["document"])).strip()[:260],
                score=round(rec.get("final_score", rec["score"]), 3),
            )
        )
    return citations


# ── 本地关键词检索（回退路径，同样享受 MQE 和相邻扩展）─────────────

def _retrieve_from_local_docs(query: str, top_k: int) -> list[Citation]:
    """本地回退检索：使用 BM25 + 相邻扩展。"""
    bm25 = _get_bm25()
    variants = _mqe_expand_llm(query)

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        for rec in bm25.search(variant, top_k=top_k):
            rid = str(rec["id"])
            if rid not in seen:
                seen.add(rid)
                all_records.append(rec)

    if all_records:
        all_records = _expand_adjacent_chunks(all_records)

    citations: list[Citation] = []
    for rec in all_records[:top_k]:
        metadata = rec.get("metadata", {})
        citations.append(
            Citation(
                doc_id=str(metadata.get("doc_id", "unknown")),
                title=str(metadata.get("title", "未知文档")),
                chunk_id=str(rec["id"]),
                snippet=re.sub(r"\s+", " ", str(rec["document"])).strip()[:260],
                score=round(rec.get("score", 0), 3),
            )
        )
    return citations



# ── 旧接口兼容 ───────────────────────────────────────────────────────

def query_rewrite(query: str) -> list[str]:
    """旧接口兼容：返回 MQE 扩展结果。"""
    return _mqe_expand_llm(query)
