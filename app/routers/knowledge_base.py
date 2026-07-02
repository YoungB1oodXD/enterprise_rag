import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.db.session import get_session
from app.db.models import User, KnowledgeBase, Document
from app.api.schemas import KnowledgeBaseCreateRequest, KnowledgeBaseResponse, DocumentResponse
from app.core.auth import get_current_user
from app.core.es_client import es
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/knowledge_base", tags=["知识库"])


@router.post("", response_model=KnowledgeBaseResponse, summary="创建知识库")
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


@router.get("/list", response_model=List[KnowledgeBaseResponse], summary="知识库列表")
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


@router.delete("/{knowledge_id}", summary="删除知识库")
def delete_knowledge_base(knowledge_id: int, current_user: User = Depends(get_current_user)):
    start_time = time.time()

    # 清理 ES 数据（先于 DB 删除，ES 失败不阻塞 DB 操作）
    try:
        for index in [settings.es.index_chunk_info, settings.es.index_document_meta]:
            if es.indices.exists(index=index):
                res = es.delete_by_query(
                    index=index,
                    body={"query": {"term": {"knowledge_id": knowledge_id}}},
                    refresh=True,
                )
                logger.info(f"ES 索引 {index} 清理完成，删除 {res.get('deleted', 0)} 条记录")
    except Exception as e:
        logger.warning(f"ES 清理失败（不影响数据库删除）: {e}")

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


@router.get("/{knowledge_id}/documents",
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
