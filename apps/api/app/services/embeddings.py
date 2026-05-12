import httpx

from app.core.config import settings


class EmbeddingError(RuntimeError):
    pass


def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.embedding_provider != "siliconflow":
        raise EmbeddingError(f"Unsupported embedding provider: {settings.embedding_provider}")
    if not settings.siliconflow_api_key:
        raise EmbeddingError("SILICONFLOW_API_KEY is required for embedding.")
    if not texts:
        return []

    response = httpx.post(
        f"{settings.llm_base_url.rstrip('/')}/embeddings",
        headers={
            "Authorization": f"Bearer {settings.siliconflow_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.embedding_model,
            "input": texts,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    return [item["embedding"] for item in payload["data"]]


def embed_texts_in_batches(texts: list[str], batch_size: int | None = None) -> list[list[float]]:
    size = batch_size or settings.embedding_batch_size
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), size):
        embeddings.extend(embed_texts(texts[start : start + size]))
    return embeddings
