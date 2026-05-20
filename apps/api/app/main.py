import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.core.config import settings

app = FastAPI(
    title="Ecommerce After-sales Copilot API",
    version="0.1.0",
    description="FastAPI service layer for the Agent workflow.",
)

# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常拦截器处理
# 拦截500
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR", 
                "message": "服务器内部错误，请稍后重试。",
                "detail": str(exc)
            }
        }
    )

# 拦截422
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR", 
                "message": "请求参数校验失败", 
                "detail": exc.errors()
            }
        }
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "agent-api"}

# 挂载子路由
app.include_router(chat_router, prefix="/api", tags=["chat"])
