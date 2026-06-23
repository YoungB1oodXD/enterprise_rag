"""
统一 LLM 客户端管理（OpenAI 兼容接口）

集中管理 OpenAI 客户端实例，避免多个模块各自创建客户端。
所有模块通过此模块获取客户端，确保连接池复用。
"""
from openai import OpenAI

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_client = None


def get_llm_client() -> OpenAI:
    """
    懒加载单例：首次调用时初始化，后续复用。
    """
    global _client
    if _client is not None:
        return _client

    if not settings.rag.llm_api_key:
        raise ValueError(
            "LLM API Key 未配置！\n"
            "请设置环境变量：DASHSCOPE_API_KEY 或 LLM_API_KEY"
        )

    _client = OpenAI(
        api_key=settings.rag.llm_api_key,
        base_url=settings.rag.llm_base_url,
    )
    logger.info("LLM 客户端初始化成功")
    return _client
