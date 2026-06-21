# app/api/schemas.py
"""
API 请求/响应数据结构

设计原则：
1. 所有接口统一返回格式：request_id + response_code + response_msg + processing_time
2. 业务字段放在各自的 Response 里
3. process_status 表示文档处理状态，前端可以用来轮询
"""
import uuid
from enum import Enum
from typing import Union, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator


# ==========================================
# 通用基类
# ==========================================
class BaseResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="请求唯一ID")
    response_code: int = Field(description="200=成功，4xx=客户端错误，5xx=服务端错误")
    response_msg: str = Field(description="响应描述")
    processing_time: float = Field(description="接口耗时（秒）")


# ==========================================
# 认证
# ==========================================
class LoginRequest(BaseModel):
    username: str = Field(description="用户名")
    password: str = Field(description="密码")


class LoginResponse(BaseModel):
    access_token: str = Field(description="JWT token")
    token_type: str = Field(default="bearer")
    username: str = Field(description="用户名")


# ==========================================
# 知识库
# ==========================================
class KnowledgeBaseCreateRequest(BaseModel):
    title: str = Field(description="知识库名称")
    category: str = Field(description="知识库类型，如：法规/政策/通知")


class KnowledgeBaseResponse(BaseResponse):
    knowledge_id: int = Field(description="知识库ID")
    title: str
    category: str


# ==========================================
# 文档
# ==========================================
class DocumentResponse(BaseResponse):
    document_id: int = Field(description="文档ID")
    knowledge_id: int
    title: str
    category: str
    file_type: str
    process_status: str = Field(description="文档解析状态: pending/processing/completed/failed")


# ==========================================
# Embedding / Rerank
# ==========================================
class EmbeddingRequest(BaseModel):
    text: Union[str, List[str]]
    model: Optional[str] = None


class EmbeddingResponse(BaseResponse):
    vector: List[List[float]]


class RerankRequest(BaseModel):
    text_pair: List[Tuple[str, str]] = Field(description="[(query, chunk), ...]")
    model: Optional[str] = None


class RerankResponse(BaseResponse):
    scores: List[float]


# ==========================================
# RAG 问答
# ==========================================

class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class ChatMessage(BaseModel):
    role: MessageRole = Field(description="消息角色：user / assistant / system")
    content: str = Field(description="消息内容")

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("消息内容不能为空")
        return v.strip()  # 顺便去掉首尾空白


class RAGRequest(BaseModel):
    knowledge_id: int = Field(description="在哪个知识库里检索")
    messages: List[ChatMessage] = Field(
        description="对话历史，最后一条必须是 role=user 的消息"
    )

    @field_validator("messages")
    @classmethod
    def last_message_must_be_user(cls, v: list) -> list:
        if not v:
            raise ValueError("对话历史不能为空")
        if v[-1].role != MessageRole.user:
            raise ValueError("对话历史的最后一条消息必须是用户消息（role=user）")
        return v


class RAGSource(BaseModel):
    """答案溯源：告诉用户这段回答来自哪个文档的哪一页"""
    document_id: int
    document_name: str = Field(description="文档标题，从数据库反查的真实名称")
    page_number: int
    chunk_content: str = Field(description="原文片段，用户可自行核验")


class RAGResponse(BaseResponse):
    answer: str = Field(description="LLM 生成的回答")
    sources: List[RAGSource] = Field(description="答案来源列表，支持溯源核验")
    messages: List[ChatMessage] = Field(description="包含本轮回答的完整对话历史")
