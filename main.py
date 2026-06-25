# main.py
import json
import time
import os
import uuid
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from typing import List

from app.core.config import settings
from app.core.logger import get_logger
from app.core.auth import get_current_user, hash_password, verify_password, create_access_token
from app.core.es_client import es
from app.db.session import get_session
from app.db.models import KnowledgeBase, Document, Conversation, ConversationMessage, User
from app.api.schemas import (
    KnowledgeBaseCreateRequest, KnowledgeBaseResponse,
    DocumentResponse, RAGRequest, RAGStreamRequest, RAGResponse, ChatMessage,
    LoginRequest, RegisterRequest, LoginResponse,
    ConversationResponse, ConversationMessageResponse, ConversationDetailResponse, ConversationListResponse,
    CreateConversationRequest, UpdateConversationRequest,
)
from app.api.schemas import RAGSource as RAGSourceSchema
from app.services.document_processor import process_document_background
from app.services.qa_service import chat_with_knowledge_base, stream_chat_with_knowledge_base

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

UPLOAD_DIR = settings.base_dir / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # 纯文本
    "text/plain",
    "text/markdown",
    # CSV
    "text/csv",
    "application/csv",
    # Excel
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    # JSON / JSONL
    "application/json",
    "application/x-ndjson",
    "application/jsonl",
}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


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
# 8. 健康检查
# ==========================================
@app.get("/health", summary="健康检查")
def health_check():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    logger.info("启动 RAG Enterprise 问答系统...")
    from app.core.es_client import init_es
    init_es()
    uvicorn.run(app, host=settings.app.host, port=settings.app.port)