from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.core.config import settings

app = FastAPI(
    title="Ecommerce After-sales Copilot API",
    version="0.1.0",
    description="FastAPI service layer for the Agent workflow.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "agent-api"}


app.include_router(chat_router, prefix="/api", tags=["chat"])
