import os
import time
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import get_session
from app.db.models import User, KnowledgeBase, Document
from app.api.schemas import DocumentResponse
from app.core.auth import get_current_user
from app.core.es_client import es
from app.services.document_processor import process_document_background

router = APIRouter(prefix="/v1/document", tags=["文档"])

logger = get_logger(__name__)

UPLOAD_DIR = settings.base_dir / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/json",
    "application/x-ndjson",
    "application/jsonl",
}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


@router.post("", response_model=DocumentResponse, summary="上传文档并后台解析")
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


@router.get("/{document_id}", response_model=DocumentResponse, summary="查询文档处理状态")
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


@router.get("/{document_id}/file", summary="获取文档原始文件")
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


@router.delete("/{document_id}", response_model=DocumentResponse, summary="删除文档并清理ES数据")
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
    try:
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
                refresh=True
            )
            deleted_count = es_response.get("deleted", 0)
            logger.info(f"ES 清理完成：文档 {document_id} 共删除 {deleted_count} 个 chunk")
    except Exception as e:
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
