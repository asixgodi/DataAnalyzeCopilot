import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.core.config import settings  # noqa: E402
from app.services.chroma_store import reset_collection, upsert_chunks  # noqa: E402
from app.services.chunking import load_document_chunks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Markdown documents into Chroma.")
    parser.add_argument("--reset", action="store_true", help="Delete and recreate the Chroma collection before ingesting.")
    parser.add_argument("--dry-run", action="store_true", help="Only print chunk information, without calling embedding API.")
    parser.add_argument("--strategy", default=settings.chunk_strategy, help="fixed, recursive, sentence, or markdown_heading.")
    parser.add_argument("--chunk-size", type=int, default=settings.chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=settings.chunk_overlap)
    args = parser.parse_args()

    documents_dir = settings.resolve_api_path(settings.documents_dir)
    chunks = load_document_chunks(
        documents_dir=documents_dir,
        strategy=args.strategy,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    if not chunks:
        print(f"No markdown documents found in {documents_dir}")
        return 1

    if args.dry_run:
        print(f"Loaded {len(chunks)} chunks from {documents_dir}")
        for chunk in chunks:
            print(f"- {chunk.id} | {chunk.metadata['title']} | {len(chunk.text)} chars")
        return 0

    if args.reset:
        reset_collection()

    count = upsert_chunks(chunks)
    print(
        f"Ingested {count} chunks into collection '{settings.collection_name}' "
        f"with strategy '{args.strategy}'."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
