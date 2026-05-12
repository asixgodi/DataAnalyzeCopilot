import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextChunk:
    id: str
    text: str
    metadata: dict[str, str | int]


def read_markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("# ").strip()
    return fallback


def normalize_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def split_fixed(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(end - chunk_overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def split_recursive(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    separators = ["\n\n", "\n", "。", "；", "，", " "]
    pieces = _recursive_split(text, chunk_size, separators)
    return _merge_small_pieces(pieces, chunk_size, chunk_overlap)


def split_by_sentence(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？!?；;])", text) if piece.strip()]
    return _merge_small_pieces(pieces, chunk_size, chunk_overlap)


def split_markdown_heading(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            _append_meaningful_section(sections, "\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        _append_meaningful_section(sections, "\n".join(current).strip())

    chunks: list[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            chunks.append(section)
        else:
            chunks.extend(split_recursive(section, chunk_size, chunk_overlap))
    return [chunk for chunk in chunks if chunk]


def _append_meaningful_section(sections: list[str], section: str) -> None:
    body = re.sub(r"^#+\s+.*$", "", section, flags=re.MULTILINE).strip()
    if body:
        sections.append(section)


def chunk_markdown_file(path: Path, strategy: str, chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    text = normalize_text(path.read_text(encoding="utf-8"))
    title = read_markdown_title(text, path.stem)
    if strategy == "fixed":
        raw_chunks = split_fixed(text, chunk_size, chunk_overlap)
    elif strategy == "recursive":
        raw_chunks = split_recursive(text, chunk_size, chunk_overlap)
    elif strategy == "sentence":
        raw_chunks = split_by_sentence(text, chunk_size, chunk_overlap)
    elif strategy == "markdown_heading":
        raw_chunks = split_markdown_heading(text, chunk_size, chunk_overlap)
    else:
        raise ValueError(f"Unsupported chunk strategy: {strategy}")

    chunks: list[TextChunk] = []
    for index, chunk in enumerate(raw_chunks):
        chunks.append(
            TextChunk(
                id=f"{path.stem}-{index}",
                text=chunk,
                metadata={
                    "doc_id": path.stem,
                    "title": title,
                    "source": path.name,
                    "chunk_index": index,
                    "strategy": strategy,
                },
            )
        )
    return chunks


def load_document_chunks(documents_dir: Path, strategy: str, chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    if not documents_dir.exists():
        return []

    chunks: list[TextChunk] = []
    for path in sorted(documents_dir.glob("*.md")):
        chunks.extend(chunk_markdown_file(path, strategy, chunk_size, chunk_overlap))
    return chunks


def _recursive_split(text: str, chunk_size: int, separators: list[str]) -> list[str]:
    if len(text) <= chunk_size:
        return [text.strip()]
    if not separators:
        return split_fixed(text, chunk_size, 0)

    separator = separators[0]
    parts = text.split(separator)
    if len(parts) == 1:
        return _recursive_split(text, chunk_size, separators[1:])

    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        value = part if separator == " " else part + separator
        if len(value) <= chunk_size:
            chunks.append(value.strip())
        else:
            chunks.extend(_recursive_split(value, chunk_size, separators[1:]))
    return chunks


def _merge_small_pieces(pieces: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{piece}" if not current else f"{current}\n{piece}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
        current = piece
    if current:
        chunks.append(current.strip())

    if chunk_overlap <= 0 or len(chunks) <= 1:
        return chunks

    overlapped: list[str] = []
    previous_tail = ""
    for chunk in chunks:
        value = f"{previous_tail}\n{chunk}".strip() if previous_tail else chunk
        overlapped.append(value)
        previous_tail = chunk[-chunk_overlap:]
    return overlapped
