import math
import re

from app.core.config import settings
from app.schemas.chat import Citation
from app.services.chroma_store import query_chroma
from app.services.chunking import TextChunk, load_document_chunks


def tokenize(text: str) -> set[str]:
    terms = set(re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}", text.lower()))
    domain_terms = [
        "退款",
        "售后",
        "尺码",
        "色差",
        "退款率",
        "工单",
        "指标",
        "政策",
        "sop",
        "服装",
        "鞋靴",
        "面料",
    ]
    for term in domain_terms:
        if term in text.lower():
            terms.add(term)
    return terms


def query_rewrite(query: str) -> list[str]:
    variants = [query]
    if "退款率" in query or "为什么" in query:
        variants.extend(["退款率 指标 口径 退款原因", "售后政策 尺码 色差 面料 质量问题"])
    if "工单" in query or "客服" in query:
        variants.append("客服工单分类 售后处理 SOP")
    return list(dict.fromkeys(variants))


def retrieve_docs(query: str, top_k: int | None = None) -> list[Citation]:
    if settings.vector_store == "chroma":
        try:
            return _retrieve_from_chroma(query, top_k or settings.top_k)
        except Exception:
            return _retrieve_from_local_docs(query, top_k or settings.top_k)
    return _retrieve_from_local_docs(query, top_k or settings.top_k)


def _retrieve_from_chroma(query: str, top_k: int) -> list[Citation]:
    records = query_chroma(query, top_k)
    citations: list[Citation] = []
    for record in records:
        metadata = record["metadata"]
        citations.append(
            Citation(
                doc_id=str(metadata.get("doc_id", "unknown")),
                title=str(metadata.get("title", "未知文档")),
                chunk_id=str(record["id"]),
                snippet=re.sub(r"\s+", " ", str(record["document"])).strip()[:260],
                score=float(record["score"]),
            )
        )
    return citations


def _retrieve_from_local_docs(query: str, top_k: int) -> list[Citation]:
    documents_dir = settings.resolve_api_path(settings.documents_dir)
    chunks = load_document_chunks(
        documents_dir=documents_dir,
        strategy=settings.chunk_strategy,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    query_tokens = set().union(*(tokenize(item) for item in query_rewrite(query)))
    scored: list[tuple[float, TextChunk]] = []
    for chunk in chunks:
        chunk_tokens = tokenize(chunk.text)
        overlap = len(query_tokens & chunk_tokens)
        if overlap == 0:
            continue
        score = overlap / math.sqrt(max(len(chunk_tokens), 1))
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    citations: list[Citation] = []
    for score, chunk in scored[:top_k]:
        citations.append(
            Citation(
                doc_id=str(chunk.metadata["doc_id"]),
                title=str(chunk.metadata["title"]),
                chunk_id=chunk.id,
                snippet=re.sub(r"\s+", " ", chunk.text).strip()[:260],
                score=round(score, 3),
            )
        )
    return citations
