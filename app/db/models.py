# app/db/models.py
"""
数据库 ORM 模型

存什么：知识库和文档的元信息（名称、路径、状态等）
不存什么：文档内容和向量——这些在 ES 里

process_status 字段是关键设计：
  pending   → 文档刚上传，还没解析
  processing → 后台正在解析
  completed  → 解析完成，可以检索
  failed     → 解析失败
这样前端可以轮询文档状态，用户知道文档是否可用
"""
import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text as sa_text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """用户表"""
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    create_dt = Column(DateTime, default=datetime.datetime.now)


class KnowledgeBase(Base):
    """知识库表：一个知识库包含多个文档"""
    __tablename__ = "knowledge_base"

    knowledge_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=True, comment="所属用户")
    title = Column(String(255), nullable=False, comment="知识库名称")
    category = Column(String(100), nullable=False, comment="知识库类型，如：法规/政策/通知")
    create_dt = Column(DateTime, default=datetime.datetime.now)
    update_dt = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<KnowledgeBase id={self.knowledge_id} title={self.title}>"


class Document(Base):
    """文档表：一个文档属于一个知识库"""
    __tablename__ = "document"

    document_id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge_base.knowledge_id"), nullable=False)
    title = Column(String(255), nullable=False, comment="文档标题")
    category = Column(String(100), comment="文档分类")
    file_path = Column(String(500), comment="文件在服务器上的存储路径")
    file_type = Column(String(100), comment="文件 MIME 类型，如 application/pdf")
    # 文档解析是异步的，这个字段记录当前状态
    process_status = Column(String(20), default="pending",
                            comment="pending / processing / completed / failed")
    error_msg = Column(String(500), comment="解析失败时的错误信息")
    create_dt = Column(DateTime, default=datetime.datetime.now)
    update_dt = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")

    def __repr__(self):
        return f"<Document id={self.document_id} title={self.title} status={self.process_status}>"


class Conversation(Base):
    """对话会话表：一次问答会话包含多条消息"""
    __tablename__ = "conversation"

    conversation_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, comment="所属用户")
    knowledge_id = Column(Integer, ForeignKey("knowledge_base.knowledge_id"), nullable=False, comment="关联知识库")
    title = Column(String(255), default="新对话", comment="会话标题，自动根据首条问题生成")
    create_dt = Column(DateTime, default=datetime.datetime.now)
    update_dt = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan",
                            order_by="ConversationMessage.create_dt.asc()")

    def __repr__(self):
        return f"<Conversation id={self.conversation_id} title={self.title}>"


class ConversationMessage(Base):
    """会话消息表：一条对话中的单条消息"""
    __tablename__ = "conversation_message"

    message_id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversation.conversation_id"), nullable=False)
    role = Column(String(20), nullable=False, comment="user / assistant")
    content = Column(sa_text, nullable=False, comment="消息内容")
    sources = Column(sa_text, nullable=True, comment="assistant 消息的溯源信息（JSON 序列化的 RAGSource[]）")
    create_dt = Column(DateTime, default=datetime.datetime.now)

    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        return f"<ConversationMessage id={self.message_id} role={self.role}>"
