import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextChunk:
    id: str
    text: str
    metadata: dict[str, str | int]

# 在切分单文件前，先抽取大标题（一级标题）
def read_markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("# ").strip()
    return fallback

# 清洗数据，去除多余的空行，保持文本整洁
def normalize_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())

# 固定长度切分
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

# 递归字符切分
def split_recursive(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    separators = ["\n\n", "\n", "。", "；", "，", " "]
    pieces = _recursive_split(text, chunk_size, separators)
    return _merge_small_pieces(pieces, chunk_size, chunk_overlap)

# 基于标点切分，并合并小片段
def split_by_sentence(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？!?；;])", text) if piece.strip()]
    return _merge_small_pieces(pieces, chunk_size, chunk_overlap)

# 基于 Markdown 二级标题切分，保持标题与内容的关联性，并对过长的部分进行递归切分
def split_markdown_heading(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    # 最终收集好的章节列表，current 用来临时存储当前章节内容
    sections: list[str] = []
    current: list[str] = []
    # 按照行遍历文本，遇到二级标题（## ）时，将之前收集的内容作为一个章节添加到 sections 中，并开始新的章节
    for line in text.splitlines():
        if line.startswith("## ") and current:
            _append_meaningful_section(sections, "\n".join(current).strip())
            # 这个libe是一个二级标题，作为新章节的开始，所以 current 重新开始收集
            current = [line]
        else:
            current.append(line)
    if current:
        _append_meaningful_section(sections, "\n".join(current).strip())

    # 对每个章节进行长度检查，如果章节长度超过 chunk_size，则使用递归切分函数进一步切分，否则直接作为一个 chunk 添加到结果中
    chunks: list[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            chunks.append(section)
        else:
            chunks.extend(split_recursive(section, chunk_size, chunk_overlap))
    return [chunk for chunk in chunks if chunk]

# 先判断当前章节是否有实际内容（去除标题等格式化文本），如果有内容才添加到 sections 中，避免生成大量无意义的空章节
def _append_meaningful_section(sections: list[str], section: str) -> None:
    body = re.sub(r"^#+\s+.*$", "", section, flags=re.MULTILINE).strip()
    if body:
        sections.append(section)

# 将一个单独的文件，拆分成多个chunk
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

# 加载文档目录下的 Markdown 文件，切分成文本块，并返回 TextChunk 列表
def load_document_chunks(documents_dir: Path, strategy: str, chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    if not documents_dir.exists():
        return []

    chunks: list[TextChunk] = []
    # chunks.extend，如果使用append，chunks会变成二维列表，extend的意思是展开并追加
    for path in sorted(documents_dir.glob("*.md")):
        chunks.extend(chunk_markdown_file(path, strategy, chunk_size, chunk_overlap))
    return chunks

# 递归切分文本，优先使用较大的分隔符，真正递归切分的函数
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

# 合并过小的片段，保持上下文连贯性，并根据 chunk_overlap 添加重叠内容
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
