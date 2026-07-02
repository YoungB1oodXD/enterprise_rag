import json
import time
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.db.session import get_session
from app.db.models import User, KnowledgeBase, Conversation, ConversationMessage
from app.api.schemas import RAGRequest, RAGStreamRequest, RAGResponse, ChatMessage
from app.core.auth import get_current_user
from app.core.logger import get_logger
from app.services.qa_service import chat_with_knowledge_base, stream_chat_with_knowledge_base

router = APIRouter(prefix="/chat", tags=["问答"])

logger = get_logger(__name__)


@router.post("", response_model=RAGResponse, summary="智能知识库问答")
def chat(req: RAGRequest, current_user: User = Depends(get_current_user)):
    start_time = time.time()

    if not req.messages:
        raise HTTPException(status_code=400, detail="对话历史不能为空")

    user_query = req.messages[-1].content
    if not user_query.strip():
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    # 验证知识库归属
    with get_session() as session:
        kb = session.query(KnowledgeBase).filter(
            KnowledgeBase.knowledge_id == req.knowledge_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")

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


@router.post("/stream", summary="智能知识库问答（流式打字机效果，支持对话持久化）")
def chat_stream(req: RAGStreamRequest, current_user: User = Depends(get_current_user)):
    if not req.messages:
        raise HTTPException(status_code=400, detail="对话历史不能为空")

    user_query = req.messages[-1].content
    if not user_query.strip():
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    # 验证知识库归属（无论是否传 conversation_id 都检查）
    with get_session() as session:
        kb = session.query(KnowledgeBase).filter(
            KnowledgeBase.knowledge_id == req.knowledge_id,
            KnowledgeBase.user_id == current_user.id,
        ).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")

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
