# app/services/qa_service.py
import traceback
from typing import List, Dict, Tuple, Optional
import json
from typing import Generator
from app.core.config import settings
from app.core.logger import get_logger
from app.retrieval.query_rewriter import rewrite_query
from app.retrieval.searcher import hybrid_search
from app.api.schemas import RAGSource, ChatMessage

logger = get_logger(__name__)

from app.core.llm_client import get_llm_client as _get_llm_client


# ============================================================
# LLM 调用辅助函数
# ============================================================

def _call_llm(messages: list, tools: list = None) -> str:
    """
    封装 LLM 调用，返回文本回答。
    失败时返回空字符串，不抛出异常。
    """
    try:
        client = _get_llm_client()
        kwargs = dict(
            model=settings.rag.llm_model,
            messages=messages,
            temperature=settings.rag.llm_temperature,
            top_p=settings.rag.llm_top_p,
            max_tokens=settings.rag.llm_max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"LLM 调用失败:\n{traceback.format_exc()}")
        return ""


def _call_llm_with_tool(messages: list, tools: list):
    """
    调用 LLM 并处理 function calling。
    返回 (content, tool_calls)，tool_calls 为空列表时表示无工具调用。
    """
    try:
        client = _get_llm_client()
        response = client.chat.completions.create(
            model=settings.rag.llm_model,
            messages=messages,
            tools=tools,
            temperature=settings.rag.llm_temperature,
            top_p=settings.rag.llm_top_p,
            max_tokens=settings.rag.llm_max_tokens,
        )
        msg = response.choices[0].message
        return msg.content or "", msg.tool_calls or []
    except Exception as e:
        logger.error(f"LLM function calling 失败:\n{traceback.format_exc()}")
        return "", []


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


# 第二道路由：LLM 语义判断的触发关键词
# 仅在查询包含这些词时才调用 LLM 分类（避免无意义 LLM 调用）
_SQL_SEMANTIC_TRIGGERS = [
    "统计", "对话", "用户", "文档", "数量", "总数",
    "conversation", "user", "document", "knowledge_base",
]


def _classify_sql_intent(query: str) -> Optional[str]:
    """
    第二道路由：LLM 语义判断是否为数据库查询意图。

    仅在查询包含数据库相关关键词时调用 LLM 做语义分类，
    避免对纯知识库问题（法律、法规等）误判。
    返回 "sql_query" 或 None。
    """
    q = query.lower().strip()

    # 预筛：只有含数据库相关词才查 LLM
    if not any(t in q for t in _SQL_SEMANTIC_TRIGGERS):
        return None

    try:
        client = _get_llm_client()
        resp = client.chat.completions.create(
            model=settings.rag.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "判断用户问题是关于「数据库表记录」还是「知识库内容」。\n"
                        "数据库表包括：conversation（对话）、user（用户）、document（文档）、knowledge_base（知识库）。\n"
                        "如果问题是查询对话数量、用户列表、文档状态等系统数据，回答：sql\n"
                        "如果问题是咨询法律法规、政策条文等知识内容，回答：rag\n"
                        "只回复一个词。"
                    ),
                },
                {"role": "user", "content": query[:200]},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        answer = resp.choices[0].message.content.strip().lower()
        if answer == "sql":
            logger.info(f"LLM 语义路由判定为数据库查询: {query[:60]}")
            return "sql_query"
        logger.debug(f"LLM 语义路由判定为知识库查询: {query[:60]}")
        return None
    except Exception as e:
        logger.warning(f"LLM 语义路由异常（降级到 RAG）: {e}")
        return None


def _try_tool_route(query: str, history: List[ChatMessage]) -> Tuple[bool, str]:
    """
    尝试路由到工具调用。
    返回 (handled, answer)，handled=True 表示工具已处理并生成回答。

    路由策略（两道闸）：
      1. 关键词匹配 → 仅匹配明确的 SQL 语法关键词（如 SELECT, COUNT）
      2. LLM 语义路由 → 对含数据库相关关键词的问题，用 LLM 判断是否为数据库查询意图
         只有两道闸都通过才执行 SQL 工具，否则降级到 RAG 流程。
    """
    from app.agent.registry import ToolRegistry, auto_route

    registry = ToolRegistry()
    registry.initialize()

    # ── 第一道闸：关键词匹配 ─────────────────────────────────────
    tool_name = auto_route(query)

    # ── 第二道闸：LLM 语义路由 ────────────────────────────────────
    if not tool_name:
        # 没有明确 SQL 关键词 → 用 LLM 判断是否为数据库管理意图
        tool_name = _classify_sql_intent(query)

    if not tool_name:
        return False, ""

    logger.info(f"触发工具调用: {tool_name}")
    tool = registry.get(tool_name)
    if not tool:
        return False, ""

    # ── 执行工具 ─────────────────────────────────────────────────
    # 注意：即使路由判定为 SQL，LLM 在 function calling 环节仍可能拒绝调用工具
    #（因为 system prompt 要求它确认问题确实涉及数据库表）
    tool_messages = [{
        "role": "system",
        "content": (
            "你是一个数据库查询助手。根据用户的问题，生成合适的 SQL 查询语句。\n\n"
            "可用表：conversation, conversation_message, document, knowledge_base, user\n\n"
            "重要：\n"
            "1. 仅当问题明确涉及上述数据库表（如：列出用户、统计对话数、查询文档状态等）时才使用 SQL 工具。\n"
            "2. 如果问题是关于知识库内容（法规、政策、条款等），不要使用 SQL 工具，直接回复无法回答。\n"
            "3. 不了解表结构时，不要猜测表名或列名。"
        ),
    }]
    recent_history = history[:-1][-4:]
    for msg in recent_history:
        tool_messages.append({"role": msg.role.value, "content": msg.content})
    tool_messages.append({"role": "user", "content": query})

    _, tool_calls = _call_llm_with_tool(tool_messages, registry.get_openai_tools())

    if not tool_calls:
        logger.warning("工具调用失败（LLM 判定不适用 SQL），降级到 RAG 流程")
        return False, ""

    tc = tool_calls[0]
    if tc.function.name != tool_name:
        return False, ""

    import json as _json
    try:
        args = _json.loads(tc.function.arguments)
    except Exception:
        args = {}
    logger.info(f"执行工具 {tool_name}，参数: {args}")
    result = tool.execute(args)

    tool_messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }],
    })
    tool_messages.append({
        "role": "tool",
        "tool_call_id": tc.id,
        "content": result,
    })

    answer = _call_llm(tool_messages)
    if answer:
        logger.info("工具调用完成，生成回答")
        return True, answer

    logger.warning("工具调用失败（无回答），降级到 RAG 流程")
    return False, ""


def _prepare_rag(query: str, history: List[ChatMessage], knowledge_id: int):
    """
    执行 RAG 检索，构造 LLM 消息列表和溯源信息。
    返回 (messages, sources)，检索无结果时 messages 为 None。
    """
    search_query = rewrite_query(query, history)
    retrieved_docs = hybrid_search(search_query, knowledge_id)

    if not retrieved_docs:
        return None, []

    user_prompt, sources = build_prompt(query, retrieved_docs)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    recent_history = history[:-1][-6:]
    for msg in recent_history:
        messages.append({"role": msg.role.value, "content": msg.content})
    messages.append({"role": "user", "content": user_prompt})

    return messages, sources


def chat_with_knowledge_base(
        knowledge_id: int,
        query: str,
        history: List[ChatMessage],
) -> Tuple[str, List[RAGSource]]:
    """
    核心 QA 流程（非流式）：
    Try Tool → RAG 检索 → 调用 LLM → 返回答案+溯源
    """
    logger.info(f"接收到用户提问: {query}")

    # ── 初始化 LLM 客户端 ────────────────────────────────────────
    try:
        client = _get_llm_client()
    except ValueError as e:
        logger.error(str(e))
        return "系统未配置大模型 API Key，无法生成回答。", []

    # ── 1. 工具路由 ─────────────────────────────────────────────
    handled, answer = _try_tool_route(query, history)
    if handled:
        return answer, []

    # ── 2. RAG 检索 + 构造消息 ──────────────────────────────────
    messages, sources = _prepare_rag(query, history, knowledge_id)
    if messages is None:
        return "抱歉，在知识库中没有检索到与您问题相关的内容。", []

    # ── 3. 调用大模型 ────────────────────────────────────────────
    logger.info(f"调用大模型，消息共 {len(messages)} 条")
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
    """核心 QA 流程（流式）：Try Tool → RAG 检索 → 流式调用 LLM"""
    logger.info(f"[流式] 接收到提问: {query}")

    # ── 初始化 LLM 客户端 ────────────────────────────────────────
    try:
        client = _get_llm_client()
    except ValueError as e:
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        return

    # ── 1. 工具路由 ─────────────────────────────────────────────
    handled, answer = _try_tool_route(query, history)
    if handled:
        yield f"data: {json.dumps({'chunk': answer}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── 2. RAG 检索 + 构造消息 ──────────────────────────────────
    messages, sources = _prepare_rag(query, history, knowledge_id)
    if messages is None:
        yield f"data: {json.dumps({'chunk': '抱歉，在知识库中没有检索到相关内容。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── 3. 流式调用大模型 ────────────────────────────────────────
    logger.info("[流式] 开始向 LLM 请求数据流...")
    try:
        response_stream = client.chat.completions.create(
            model=settings.rag.llm_model,
            messages=messages,
            temperature=settings.rag.llm_temperature,
            top_p=settings.rag.llm_top_p,
            max_tokens=settings.rag.llm_max_tokens,
            stream=True,
        )

        for chunk in response_stream:
            delta_content = chunk.choices[0].delta.content
            if delta_content:
                yield f"data: {json.dumps({'chunk': delta_content}, ensure_ascii=False)}\n\n"

        # 发送溯源信息
        sources_dict = [s.model_dump() for s in sources]
        yield f"data: {json.dumps({'sources': sources_dict}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        logger.info("[流式] 回答流发送完毕。")
    except Exception as e:
        logger.error(f"流式调用大模型报错:\n{traceback.format_exc()}")
        yield f"data: {json.dumps({'error': '生成回答时发生系统错误。'}, ensure_ascii=False)}\n\n"