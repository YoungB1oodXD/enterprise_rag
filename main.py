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
app.include_router(auth_router)
app.include_router(knowledge_base_router)
app.include_router(document_router)
app.include_router(conversation_router)

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
# 7. RAG 问答接口（非流式）
# ==========================================
@app.post("/chat", response_model=RAGResponse, summary="智能知识库问答")
def chat(req: RAGRequest, current_user: User = Depends(get_current_user)):
    start_time = time.time()

    if not req.messages:
        raise HTTPException(status_code=400, detail="对话历史不能为空")

    user_query = req.messages[-1].content
    if not user_query.strip():
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    answer, sources = chat_with_knowledge_base(req.knowledge_id, user_query, req.messages)
    new_messages = req.messages + [ChatMessage(role="assistant", content=answer)]

    return RAGResponse(
        response_code=200,
        response_msg="回答生成成功",
        processing_time=time.time() - start_time,
        answer=answer,
        sources=sources,
        messages=new_messages
    )


# ==========================================
# 8. 流式问答接口（带对话持久化）
# ==========================================

def _persist_streaming_response(generator, conversation_id: int, user_query: str):
    """
    包装流式生成器，在 SSE 流结束后自动保存 assistant 回答到数据库。

    设计说明：
    - 生成器运行在请求 handler 返回之后，不能复用请求内的 session。
    - 每次调用 _persist_streaming_response 都会开启新的独立 session，
      确保不会出现 session 冲突。
    - 用 `with get_session()` 的上下文管理器保证自动 commit/rollback。
    """
    full_content = ""
    sources_json = None
    collected_sources = None

    for event in generator:
        # 透传所有事件，同时收集 chunk 和 sources
        if event.startswith("data: ") and not event.startswith("data: [DONE]"):
            try:
                payload = json.loads(event[6:].strip())
                if "chunk" in payload:
                    full_content += payload["chunk"]
                if "sources" in payload:
                    collected_sources = payload["sources"]
                    sources_json = json.dumps(payload["sources"], ensure_ascii=False)
            except Exception as e:
                logger.warning("SSE 事件解析失败: %s", e)

        yield event

        # 遇到结束标记后，保存 assistant 回答
        if event == "data: [DONE]\n\n" and full_content.strip():
            try:
                with get_session() as session:
                    msg = ConversationMessage(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_content,
                        sources=sources_json,
                    )
                    session.add(msg)

                    # 自动标题：如果是第一条消息（只有 1 条 user + 1 条 assistant）
                    msg_count = session.query(ConversationMessage).filter(
                        ConversationMessage.conversation_id == conversation_id
                    ).count()
                    if msg_count <= 2:  # user + assistant
                        conv = session.query(Conversation).filter(
                            Conversation.conversation_id == conversation_id
                        ).first()
                        if conv and conv.title == "新对话":
                            conv.title = (user_query[:30] + "...") if len(user_query) > 30 else user_query
            except Exception as e:
                logger.error(f"持久化会话消息失败: {e}")


@app.post("/chat/stream", summary="智能知识库问答（流式打字机效果，支持对话持久化）")
def chat_stream(req: RAGStreamRequest, current_user: User = Depends(get_current_user)):
    if not req.messages:
        raise HTTPException(status_code=400, detail="对话历史不能为空")

    user_query = req.messages[-1].content
    if not user_query.strip():
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    # 如果传入了 conversation_id，验证所有权并保存用户消息
    if req.conversation_id:
        with get_session() as session:
            conv = session.query(Conversation).filter(
                Conversation.conversation_id == req.conversation_id,
                Conversation.user_id == current_user.id,
            ).first()
            if not conv:
                raise HTTPException(status_code=404, detail="会话不存在")
            # 保存用户消息
            user_msg = ConversationMessage(
                conversation_id=req.conversation_id,
                role="user",
                content=user_query,
            )
            session.add(user_msg)

    generator = stream_chat_with_knowledge_base(req.knowledge_id, user_query, req.messages)

    if req.conversation_id:
        generator = _persist_streaming_response(generator, req.conversation_id, user_query)

    return StreamingResponse(generator, media_type="text/event-stream")


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