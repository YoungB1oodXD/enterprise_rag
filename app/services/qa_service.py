# app/services/qa_service.py
import traceback
from typing import List, Dict, Tuple
import json
from typing import Generator
from app.core.config import settings
from app.core.logger import get_logger
from app.retrieval.query_rewriter import rewrite_query
from app.retrieval.searcher import hybrid_search
from app.api.schemas import RAGSource, ChatMessage

logger = get_logger(__name__)

_llm_client = None


def _get_llm_client():
    """懒加载 LLM 客户端，第一次调用时初始化，之后复用"""
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    if not settings.rag.llm_api_key:
        raise ValueError(
            "LLM API Key 未配置！\n"
            "请设置环境变量：export DASHSCOPE_API_KEY='your-key'\n"
            "Windows PowerShell：$env:DASHSCOPE_API_KEY='your-key'"
        )

    from openai import OpenAI
    _llm_client = OpenAI(
        api_key=settings.rag.llm_api_key,
        base_url=settings.rag.llm_base_url,
    )
    logger.info("LLM 客户端初始化成功")
    return _llm_client


# ============================================================
# 政务场景的 System Prompt
#
# 设计原则：
# 1. 明确身份：告诉 LLM 它是知识库助手，不是通用聊天机器人
# 2. 硬约束：只能用参考资料回答，不能用内部知识
# 3. 拒答指令：资料不够时明确拒答，而不是强行编造
# 4. 格式要求：条理清晰，方便用户阅读
# ============================================================
SYSTEM_PROMPT = """你是一个专业的政务与企业知识库助手。
请严格遵循以下规则回答用户的问题：
1. 你必须、且只能基于提供给你的 [参考资料] 来生成答案。
2. 如果 [参考资料] 中没有提及相关信息，或者提供的资料不足以回答问题，请直接回答："抱歉，在知识库的参考资料中未找到相关内容，无法准确回答。"
3. 绝不允许编造、推测或使用你的内部知识库来回答！
4. 回答要条理清晰，简明扼要，直接切中要害。
"""


def _fetch_document_names(doc_ids: List[int]) -> Dict[int, str]:
    """
        批量从数据库查询文档标题。
        返回 {document_id: title} 字典。
        查询失败时返回空字典，调用方用 doc_id 兜底。
    """
    if not doc_ids:
        return {}
    try:
        from app.db.session import get_session
        from app.db.models import Document

        with get_session() as session:
            docs = session.query(Document.document_id, Document.title).filter(
                Document.document_id.in_(doc_ids)

            ).all()
            return {doc.document_id: doc.title for doc in docs}
    except Exception:
        logger.warning(f"反查文档名失败，将使用文档ID代替:\n{traceback.format_exc()}")
        return {}


def build_prompt(query: str, retrieved_docs: List[Dict]) -> Tuple[str, List[RAGSource]]:
    """
    将检索到的文档块拼接成 Prompt，同时提取溯源信息。

    返回：
    - user_prompt: 发给 LLM 的完整用户消息
    - sources:     溯源列表，返回给前端展示
    """
    if not retrieved_docs:
        return "", []
    all_doc_ids = list({doc.get("document_id", 0) for doc in retrieved_docs})
    doc_name_map = _fetch_document_names(all_doc_ids)


    context_str = ""
    sources = []

    for i, doc in enumerate(retrieved_docs):
        content = doc.get("chunk_content", "")
        breadcrumb = doc.get("breadcrumb", "未知章节")
        doc_id = doc.get("document_id", 0)
        page_number = doc.get("page_number", 1)

        # 优先用数据库查到的真实文档名，查不到才用 ID 兜底
        doc_name = doc_name_map.get(doc_id, f"文档_{doc_id}")

        context_str += f"--- 资料 [{i + 1}] ---\n"
        context_str += f"来源：{doc_name}｜章节：{breadcrumb}｜第{page_number}页\n"
        context_str += f"内容：{content}\n\n"

        sources.append(RAGSource(
            document_id=doc_id,
            document_name=doc_name,
            page_number=page_number,
            chunk_content=content,
        ))

    user_prompt = f"""请基于以下 [参考资料] 回答问题。

[参考资料]:
{context_str}
[用户问题]:
{query}
"""
    return user_prompt, sources


def chat_with_knowledge_base(
        knowledge_id: int,
        query: str,
        history: List[ChatMessage],
) -> Tuple[str, List[RAGSource]]:
    """
    核心 QA 流程：
    P0: 混合检索 -> 组装Prompt -> 调用LLM -> 返回答案+溯源
    P1新增: Query Rewrite + 真实文档名 + history传入LLM
    """
    # ── 初始化 LLM 客户端 ────────────────────────────────────────
    try:
        client = _get_llm_client()
    except ValueError as e:
        logger.error(str(e))
        return "系统未配置大模型 API Key，无法生成回答。", []

    # ── 1. Query Rewrite：多轮对话时先改写再检索 ─────────────────
    logger.info(f"接收到用户提问: {query}")
    search_query = rewrite_query(query, history)

    # ── 2. 混合检索 + Rerank ─────────────────────────────────────
    retrieved_docs = hybrid_search(search_query, knowledge_id)

    if not retrieved_docs:
        return "抱歉，在知识库中没有检索到与您问题相关的内容。", []

    # ── 3. 组装 Prompt 和溯源列表 ────────────────────────────────
    user_prompt, sources = build_prompt(query, retrieved_docs)

    # ── 4. 构造发给 LLM 的完整消息列表 ──────────────────────────
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # history[:-1] 去掉最后一条（当前用户提问），[-6:] 取最近6条
    recent_history = history[:-1][-6:]

    for msg in recent_history:
        messages.append({
            "role": msg.role.value,
            "content": msg.content,
        })

    # 最后加入当前轮的用户提问（用带 context 的 user_prompt）
    messages.append({"role": "user", "content": user_prompt})

    # ── 5. 调用千问大模型 ────────────────────────────────────────
    logger.info(f"调用大模型，消息共 {len(messages)} 条（含历史 {len(recent_history)} 条）")
    try:
        response = client.chat.completions.create(
            model=settings.rag.llm_model,
            messages=messages,
            temperature=settings.rag.llm_temperature,
            top_p=settings.rag.llm_top_p,
            max_tokens=settings.rag.llm_max_tokens,
        )
        answer = response.choices[0].message.content
        logger.info("大模型回答生成完毕")
        return answer, sources

    except Exception as e:
        logger.error(f"调用大模型报错:\n{traceback.format_exc()}")
        return "生成回答时发生系统错误，请稍后重试。", sources


def stream_chat_with_knowledge_base(
        knowledge_id: int,
        query: str,
        history: List[ChatMessage],
) -> Generator[str, None, None]:
    try:
        client = _get_llm_client()
    except ValueError as e:
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        return

    # 1. Query Rewrite
    logger.info(f"[流式] 接收到提问: {query}")
    search_query = rewrite_query(query, history)

    # 2. 混合检索
    retrieved_docs = hybrid_search(search_query, knowledge_id)
    if not retrieved_docs:
        yield f"data: {json.dumps({'chunk': '抱歉，在知识库中没有检索到相关内容。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # 3. 组装 Prompt 和 溯源
    user_prompt, sources = build_prompt(query, retrieved_docs)

    # 4. 构造消息
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    recent_history = history[:-1][-6:]
    for msg in recent_history:
        messages.append({"role": msg.role.value, "content": msg.content})
    messages.append({"role": "user", "content": user_prompt})

    # 5. 流式调用大模型 (注意这里的 stream=True)
    logger.info("[流式] 开始向 LLM 请求数据流...")
    try:
        response_stream = client.chat.completions.create(
            model=settings.rag.llm_model,
            messages=messages,
            temperature=settings.rag.llm_temperature,
            top_p=settings.rag.llm_top_p,
            max_tokens=settings.rag.llm_max_tokens,
            stream=True
        )

        # 核心循环：只要大模型吐出一个字，就立刻发给前端
        for chunk in response_stream:
            delta_content = chunk.choices[0].delta.content
            if delta_content:
                # 包装成 SSE 格式：data: {"chunk": "你"} \n\n
                yield f"data: {json.dumps({'chunk': delta_content}, ensure_ascii=False)}\n\n"

        # 6. 当文字全部吐完后，把溯源信息发给前端
        sources_dict = [s.model_dump() for s in sources]
        yield f"data: {json.dumps({'sources': sources_dict}, ensure_ascii=False)}\n\n"

        # 7. 发送结束标记
        yield "data: [DONE]\n\n"
        logger.info("[流式] 回答流发送完毕。")

    except Exception as e:
        logger.error(f"流式调用大模型报错:\n{traceback.format_exc()}")
        yield f"data: {json.dumps({'error': '生成回答时发生系统错误。'}, ensure_ascii=False)}\n\n"