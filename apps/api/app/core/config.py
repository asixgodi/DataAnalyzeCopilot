from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


API_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    siliconflow_api_key: str = ""
    llm_provider: str = "siliconflow"
    llm_base_url: str = "https://api.siliconflow.cn/v1"
    llm_model: str = "deepseek-ai/DeepSeek-V3"

    embedding_provider: str = "siliconflow"
    embedding_model: str = "Pro/BAAI/bge-m3"
    embedding_batch_size: int = 16

    vector_store: str = "chroma"
    chroma_persist_dir: str = "../../data/vector_store/chroma"
    collection_name: str = "after_sales_knowledge"

    database_url: str = "sqlite:///../../data/demo.db"
    documents_dir: str = "../../data/documents"
    chunk_strategy: str = "markdown_heading"
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 5

    rag_enable_mqe: bool = True
    rag_enable_bm25: bool = True
    rag_enable_rrf: bool = True
    rag_enable_rerank: bool = True
    rag_enable_adjacent_context: bool = True
    rag_enable_router: bool = True
    rag_router_mode: str = "rule"
    rag_router_confidence_threshold: float = 0.65
    agent_router_mode: str = "hybrid"
    agent_router_confidence_threshold: float = 0.88
    agent_enable_answer_guard: bool = True
    agent_global_timeout: float = 60.0  # Agent 全局超时（秒）

    # LangSmith 可观测性
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "copilot"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def resolve_api_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (API_DIR / path).resolve()


settings = Settings()
