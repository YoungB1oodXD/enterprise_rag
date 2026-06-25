# main.py
import uuid
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="RAG Enterprise - 企业级智能知识库问答系统", version="2.0.0")

# 启动时检查 JWT 密钥配置
from app.core.auth import SECRET_KEY as _jwt_secret
if _jwt_secret == "rag-enterprise-secret-key-change-in-production":
    logger.warning("JWT 使用默认密钥，请设置 JWT_SECRET_KEY 环境变量")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers.auth import router as auth_router
from app.routers.knowledge_base import router as knowledge_base_router
from app.routers.document import router as document_router
from app.routers.conversation import router as conversation_router
from app.routers.chat import router as chat_router
app.include_router(auth_router)
app.include_router(knowledge_base_router)
app.include_router(document_router)
app.include_router(conversation_router)
app.include_router(chat_router)


# ==========================================
# 全局异常处理
# ==========================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = str(uuid.uuid4())
    logger.error(
        f"未捕获的异常 | request_id={request_id} | "
        f"path={request.url.path} | error={exc}",
        exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={
            "request_id": request_id,
            "response_code": 500,
            "response_msg": "服务内部错误，请稍后重试",
            "processing_time": 0.0,
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "request_id": str(uuid.uuid4()),
            "response_code": exc.status_code,
            "response_msg": exc.detail,
            "processing_time": 0.0,
        }
    )


# ==========================================
# 健康检查
# ==========================================
@app.get("/health", summary="健康检查")
def health_check():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    logger.info("启动 RAG Enterprise 问答系统...")
    from app.core.es_client import init_es
    init_es()
    uvicorn.run(app, host=settings.app.host, port=settings.app.port)
