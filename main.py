# main.py
import uuid
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时连接 ES、恢复卡住文档，关闭时清理"""
    # ── Startup ──
    logger.info("正在初始化 Elasticsearch...")
    from app.core.es_client import init_es
    if not init_es():
        logger.critical("Elasticsearch 连接失败，服务无法启动")
        raise RuntimeError("Elasticsearch 连接失败，请检查 ES 是否已启动")

    # 扫描重启前卡在 processing 状态的文档，重置为 pending
    from app.db.session import get_session
    from app.db.models import Document
    try:
        with get_session() as session:
            stuck = session.query(Document).filter(
                Document.process_status == "processing"
            ).all()
            if stuck:
                logger.warning(
                    f"发现 {len(stuck)} 个文档在重启时为 processing 状态，已重置为 pending"
                )
                for doc in stuck:
                    doc.process_status = "pending"
    except Exception as e:
        logger.error(f"扫描卡住文档失败: {e}")

    logger.info("RAG Enterprise 启动完成")
    yield
    # ── Shutdown ──
    logger.info("RAG Enterprise 服务关闭")


app = FastAPI(title="RAG Enterprise - 企业级智能知识库问答系统", version="2.0.0", lifespan=lifespan)

# JWT 密钥在 auth.py 导入时自动检查（无默认值，未配置则抛出异常）
from app.core.auth import SECRET_KEY as _jwt_secret  # noqa: F401
logger.info("JWT_SECRET_KEY 已配置")

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
from app.routers.evaluation import router as evaluation_router
app.include_router(auth_router)
app.include_router(knowledge_base_router)
app.include_router(document_router)
app.include_router(conversation_router)
app.include_router(chat_router)
app.include_router(evaluation_router)


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
    uvicorn.run(app, host=settings.app.host, port=settings.app.port)
