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
app.include_router(auth_router)

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
# 1. 知识库管理接口
# ==========================================
@app.post("/v1/knowledge_base", response_model=KnowledgeBaseResponse, summary="创建知识库")
def create_knowledge_base(req: KnowledgeBaseCreateRequest, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        kb = KnowledgeBase(title=req.title, category=req.category, user_id=current_user.id)
        session.add(kb)
        session.flush()
        return KnowledgeBaseResponse(
            response_code=200,
            response_msg="知识库创建成功",
            processing_time=time.time() - start_time,
            knowledge_id=kb.knowledge_id,
            title=kb.title,
            category=kb.category
        )


@app.get("/v1/knowledge_base/list", response_model=List[KnowledgeBaseResponse], summary="知识库列表")
def list_knowledge_bases(current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        kbs = session.query(KnowledgeBase).filter(
            KnowledgeBase.user_id == current_user.id
        ).order_by(KnowledgeBase.create_dt.desc()).all()

        return [
            KnowledgeBaseResponse(
                response_code=200,
                response_msg="ok",
                processing_time=time.time() - start_time,
                knowledge_id=kb.knowledge_id,
                title=kb.title,
                category=kb.category,
            )
            for kb in kbs
        ]


@app.delete("/v1/knowledge_base/{knowledge_id}", summary="删除知识库")
def delete_knowledge_base(knowledge_id: int, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        kb = session.query(KnowledgeBase).filter(
            KnowledgeBase.knowledge_id == knowledge_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        session.delete(kb)

        return KnowledgeBaseResponse(
            response_code=200,
            response_msg="知识库删除成功",
            processing_time=time.time() - start_time,
            knowledge_id=knowledge_id,
            title=kb.title,
            category=kb.category,
        )


# ==========================================
# 2. 文档上传
# ==========================================
@app.post("/v1/document", response_model=DocumentResponse, summary="上传文档并后台解析")
def upload_document(
        background_tasks: BackgroundTasks,
        knowledge_id: int = Form(..., description="所属知识库ID"),
        title: str = Form(..., description="文档标题"),
        category: str = Form("default", description="文档分类"),
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
):
    start_time = time.time()

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{file.content_type}。只支持 PDF 和 Word 文档。"
        )

    file_content = file.file.read()
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大：{len(file_content) / 1024 / 1024:.1f}MB，最大支持 50MB。"
        )

    with get_session() as session:
        kb = session.query(KnowledgeBase).filter(
            KnowledgeBase.knowledge_id == knowledge_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在，请先创建知识库")

        doc = Document(
            knowledge_id=knowledge_id,
            title=title,
            category=category,
            file_type=file.content_type,
            process_status="pending"
        )
        session.add(doc)
        session.flush()

        file_extension = os.path.splitext(file.filename)[1]
        file_path = UPLOAD_DIR / f"doc_{doc.document_id}{file_extension}"

        with open(file_path, "wb") as buffer:
            buffer.write(file_content)

        doc.file_path = str(file_path)
        session.commit()

        background_tasks.add_task(process_document_background, doc.document_id)

        return DocumentResponse(
            response_code=200,
            response_msg="文件上传成功，正在后台解析中...",
            processing_time=time.time() - start_time,
            document_id=doc.document_id,
            knowledge_id=knowledge_id,
            title=title,
            category=category,
            file_type=file.content_type,
            process_status="pending"
        )


# ==========================================
# 3. 文档状态查询
# ==========================================
@app.get("/v1/document/{document_id}", response_model=DocumentResponse, summary="查询文档处理状态")
def get_document_status(document_id: int, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        doc = session.query(Document).join(
            KnowledgeBase, Document.knowledge_id == KnowledgeBase.knowledge_id
        ).filter(
            Document.document_id == document_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")

        return DocumentResponse(
            response_code=200,
            response_msg=f"文档状态：{doc.process_status}",
            processing_time=time.time() - start_time,
            document_id=doc.document_id,
            knowledge_id=doc.knowledge_id,
            title=doc.title,
            category=doc.category or "",
            file_type=doc.file_type or "",
            process_status=doc.process_status,
        )


# ==========================================
# 3.5 文档原始文件预览
# ==========================================
@app.get("/v1/document/{document_id}/file", summary="获取文档原始文件")
def get_document_file(document_id: int, current_user: User = Depends(get_current_user)):
    """返回文档的原始文件，支持浏览器预览和下载。"""
    with get_session() as session:
        doc = session.query(Document).join(
            KnowledgeBase, Document.knowledge_id == KnowledgeBase.knowledge_id
        ).filter(
            Document.document_id == document_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not doc or not doc.file_path:
            raise HTTPException(status_code=404, detail="文件不存在")

        file_path = doc.file_path
        content_type = doc.file_type or "application/octet-stream"

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件已被删除")

    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=f"{doc.title}{os.path.splitext(file_path)[1]}",
    )


# ==========================================
# 4. 文档列表接口
# ==========================================
@app.get("/v1/knowledge_base/{knowledge_id}/documents",
         response_model=List[DocumentResponse],
         summary="查询知识库下的所有文档")
def list_documents(knowledge_id: int, current_user: User = Depends(get_current_user)):
    """返回指定知识库下的所有文档列表。"""
    with get_session() as session:
        kb = session.query(KnowledgeBase).filter(
            KnowledgeBase.knowledge_id == knowledge_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")

        docs = session.query(Document).filter(
            Document.knowledge_id == knowledge_id
        ).order_by(Document.create_dt.desc()).all()

        return [
            DocumentResponse(
                response_code=200,
                response_msg="ok",
                processing_time=0.0,
                document_id=doc.document_id,
                knowledge_id=doc.knowledge_id,
                title=doc.title,
                category=doc.category or "",
                file_type=doc.file_type or "",
                process_status=doc.process_status,
            )
            for doc in docs
        ]


# ==========================================
# 5. 文档删除接口（同步清理ES数据）
# ==========================================
@app.delete("/v1/document/{document_id}", response_model=DocumentResponse, summary="删除文档并清理ES数据")
def delete_document(document_id: int, current_user: User = Depends(get_current_user)):
    """删除文档，同时清理 ES 里的所有相关 chunk 向量数据。"""
    start_time = time.time()

    # ── Step1：从数据库查出文档信息（删除前先拿到信息备用）──────────
    with get_session() as session:
        doc = session.query(Document).join(
            KnowledgeBase, Document.knowledge_id == KnowledgeBase.knowledge_id
        ).filter(
            Document.document_id == document_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")

        # 保存到局部变量，session关闭后doc对象会失效
        doc_title    = doc.title
        doc_category = doc.category or ""
        doc_kt_id    = doc.knowledge_id
        doc_file_type = doc.file_type or ""
        doc_file_path = doc.file_path
        doc_status   = doc.process_status

    # ── Step2：删除 ES 里该文档的所有 chunk ─────────────────────────
    # ============================================================
    # 为什么用 delete_by_query 而不是逐条删？
    #   一个文档可能有几十上百个 chunk，逐条删要发几百次请求。
    #   delete_by_query 一次请求删除所有匹配的文档，效率高得多。
    # ============================================================
    try:
        # 先检查索引是否存在，不存在则跳过 ES 清理
        if not es.indices.exists(index=settings.es.index_chunk_info):
            logger.warning(f"ES 索引 {settings.es.index_chunk_info} 不存在，跳过 ES 清理")
            deleted_count = 0
        else:
            es_response = es.delete_by_query(
                index=settings.es.index_chunk_info,
                body={
                    "query": {
                        "term": {"document_id": document_id}
                    }
                },
                # refresh=True 确保删除立即生效，后续检索不会再检索到这些数据
                refresh=True
            )
            deleted_count = es_response.get("deleted", 0)
            logger.info(f"ES 清理完成：文档 {document_id} 共删除 {deleted_count} 个 chunk")
    except Exception as e:
        # ES删除失败，不继续删数据库，记录日志方便排查
        logger.error(f"ES 删除失败，终止删除操作: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"ES 数据清理失败，文档未删除：{str(e)}"
        )

    # ── Step3：删除数据库记录 ────────────────────────────────────────
    with get_session() as session:
        doc = session.query(Document).filter(
            Document.document_id == document_id
        ).first()
        if doc:
            session.delete(doc)

    # ── Step4：删除服务器上的原始文件（可选，失败不影响主流程）───────
    if doc_file_path and os.path.exists(doc_file_path):
        try:
            os.remove(doc_file_path)
            logger.info(f"原始文件已删除：{doc_file_path}")
        except Exception as e:
            # 文件删除失败不是致命错误，记录日志即可
            logger.warning(f"原始文件删除失败（不影响功能）：{e}")

    logger.info(f"文档删除成功：{doc_title} (ID: {document_id})")

    return DocumentResponse(
        response_code=200,
        response_msg=f"文档删除成功，已清理 ES 向量数据",
        processing_time=time.time() - start_time,
        document_id=document_id,
        knowledge_id=doc_kt_id,
        title=doc_title,
        category=doc_category,
        file_type=doc_file_type,
        process_status=doc_status,
    )


# ==========================================
# 6. 对话/会话管理接口
# ==========================================

@app.get("/v1/conversation/list", summary="获取知识库下的会话列表（支持搜索与分页）")
def list_conversations(
    knowledge_id: int,
    search: str = "",
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
):
    """返回指定知识库下的会话列表，支持按标题搜索和分页。"""
    with get_session() as session:
        query = session.query(Conversation).filter(
            Conversation.knowledge_id == knowledge_id,
            Conversation.user_id == current_user.id,
        )

        if search.strip():
            query = query.filter(Conversation.title.like(f"%{search.strip()}%"))

        total = query.count()

        convs = query.order_by(Conversation.update_dt.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        items = []
        for conv in convs:
            msg_count = len(conv.messages)
            items.append(ConversationResponse(
                response_code=200,
                response_msg="ok",
                processing_time=0.0,
                conversation_id=conv.conversation_id,
                knowledge_id=conv.knowledge_id,
                title=conv.title,
                message_count=msg_count,
                create_dt=conv.create_dt.isoformat(),
                update_dt=conv.update_dt.isoformat(),
            ))

        return ConversationListResponse(total=total, items=items)


@app.post("/v1/conversation", response_model=ConversationResponse, summary="创建新会话")
def create_conversation(req: CreateConversationRequest, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        conv = Conversation(
            knowledge_id=req.knowledge_id,
            user_id=current_user.id,
            title=req.title or "新对话",
        )
        session.add(conv)
        session.flush()
        return ConversationResponse(
            response_code=200,
            response_msg="会话创建成功",
            processing_time=time.time() - start_time,
            conversation_id=conv.conversation_id,
            knowledge_id=conv.knowledge_id,
            title=conv.title,
            message_count=0,
            create_dt=conv.create_dt.isoformat(),
            update_dt=conv.update_dt.isoformat(),
        )


@app.put("/v1/conversation/{conversation_id}", response_model=ConversationResponse, summary="更新会话标题")
def update_conversation(conversation_id: int, req: UpdateConversationRequest,
                        current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.conversation_id == conversation_id,
            Conversation.user_id == current_user.id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
        conv.title = req.title
        session.flush()
        return ConversationResponse(
            response_code=200,
            response_msg="会话已更新",
            processing_time=time.time() - start_time,
            conversation_id=conv.conversation_id,
            knowledge_id=conv.knowledge_id,
            title=conv.title,
            message_count=len(conv.messages),
            create_dt=conv.create_dt.isoformat(),
            update_dt=conv.update_dt.isoformat(),
        )


@app.delete("/v1/conversation/{conversation_id}", response_model=ConversationResponse, summary="删除会话")
def delete_conversation(conversation_id: int, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.conversation_id == conversation_id,
            Conversation.user_id == current_user.id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
        title = conv.title
        kt_id = conv.knowledge_id
        session.delete(conv)
        return ConversationResponse(
            response_code=200,
            response_msg="会话删除成功",
            processing_time=time.time() - start_time,
            conversation_id=conversation_id,
            knowledge_id=kt_id,
            title=title,
            message_count=0,
            create_dt="",
            update_dt="",
        )


@app.get("/v1/conversation/{conversation_id}", response_model=ConversationDetailResponse,
         summary="获取会话详情（含所有消息）")
def get_conversation(conversation_id: int, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    with get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.conversation_id == conversation_id,
            Conversation.user_id == current_user.id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")

        messages = []
        for msg in conv.messages:
            sources = None
            if msg.sources:
                try:
                    sources_data = json.loads(msg.sources)
                    sources = [RAGSourceSchema(**item) for item in sources_data]
                except Exception as e:
                    logger.warning("sources JSON 解析失败: %s", e)
            messages.append(ConversationMessageResponse(
                response_code=200,
                response_msg="ok",
                processing_time=0.0,
                message_id=msg.message_id,
                role=msg.role,
                content=msg.content,
                sources=sources,
                create_dt=msg.create_dt.isoformat(),
            ))

        return ConversationDetailResponse(
            response_code=200,
            response_msg="ok",
            processing_time=time.time() - start_time,
            conversation_id=conv.conversation_id,
            knowledge_id=conv.knowledge_id,
            title=conv.title,
            messages=messages,
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