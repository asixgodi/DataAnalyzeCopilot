from typing import Any

from app.core.config import settings
from app.services.chunking import TextChunk
from app.services.embeddings import embed_texts, embed_texts_in_batches


class ChromaUnavailable(RuntimeError):
    pass


def _import_chromadb():
    try:
        import chromadb
    except ImportError as exc:
        raise ChromaUnavailable("chromadb is not installed. Run pip install chromadb.") from exc
    return chromadb


def get_collection():
    chromadb = _import_chromadb()
    persist_dir = settings.resolve_api_path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    return client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection() -> None:
    chromadb = _import_chromadb()
    persist_dir = settings.resolve_api_path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(settings.collection_name)
    except Exception:
        pass
    client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_chunks(chunks: list[TextChunk]) -> int:
    if not chunks:
        return 0
    collection = get_collection()
    texts = [chunk.text for chunk in chunks]
    embeddings = embed_texts_in_batches(texts)
    collection.upsert(
        ids=[chunk.id for chunk in chunks],
        documents=texts,
        embeddings=embeddings,
        metadatas=[chunk.metadata for chunk in chunks],
    )
    return len(chunks)


def query_chroma(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    collection = get_collection()
    embedding = embed_texts([query])[0]
    result = collection.query(
        query_embeddings=[embedding],
        n_results=top_k or settings.top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    ids = result.get("ids", [[]])[0]

    records: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        distance = distances[index] if index < len(distances) else 1
        score = max(0.0, 1.0 - float(distance))
        metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        records.append(
            {
                "id": ids[index] if index < len(ids) else f"chunk-{index}",
                "document": document,
                "metadata": metadata,
                "score": round(score, 3),
            }
        )
    return records
