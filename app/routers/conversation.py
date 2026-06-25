import json
import time
from fastapi import APIRouter, Depends, HTTPException
from app.db.session import get_session
from app.db.models import User, Conversation, ConversationMessage
from app.api.schemas import (
    ConversationResponse, ConversationMessageResponse, ConversationDetailResponse, ConversationListResponse,
    CreateConversationRequest, UpdateConversationRequest,
)
from app.api.schemas import RAGSource as RAGSourceSchema
from app.core.auth import get_current_user
from app.core.logger import get_logger

router = APIRouter(prefix="/v1/conversation", tags=["会话"])

logger = get_logger(__name__)


@router.get("/list", summary="获取知识库下的会话列表（支持搜索与分页）")
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


@router.post("", response_model=ConversationResponse, summary="创建新会话")
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


@router.put("/{conversation_id}", response_model=ConversationResponse, summary="更新会话标题")
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


@router.delete("/{conversation_id}", response_model=ConversationResponse, summary="删除会话")
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


@router.get("/{conversation_id}", response_model=ConversationDetailResponse,
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
