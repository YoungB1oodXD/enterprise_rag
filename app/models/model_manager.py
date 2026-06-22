"""
模型管理器

支持两种模式：
1. API 模式：通过 DashScope API 调用 text-embedding-v2，无需本地模型
2. 本地模式：加载本地 Sentence-Transformers 模型

根据 embedding_model_params 中是否有 local_path 自动切换。
"""
import numpy as np
from typing import List, Union

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_embedding_model = None


def _get_lazy_llm_client():
    """复用 qa_service 的懒加载模式，初始化 OpenAI 客户端"""
    from openai import OpenAI

    if not settings.rag.llm_api_key:
        raise ValueError("DASHSCOPE_API_KEY 未配置，Embedding API 无法使用")

    return OpenAI(
        api_key=settings.rag.llm_api_key,
        base_url=settings.rag.llm_base_url,
    )


def get_embedding(text: Union[str, List[str]]) -> np.ndarray:
    """
    对文本编码，返回归一化后的向量。

    API 模式：调用 DashScope text-embedding-v2
    本地模式：加载 Sentence-Transformer 编码

    :param text: 单条文本或文本列表
    :return: shape=(n, dims) 的 numpy 数组
    """
    if isinstance(text, str):
        text = [text]

    model_params = settings.embedding_model_params.get(settings.rag.embedding_model, {})

    # API 模式（无 local_path）
    if "local_path" not in model_params:
        return _get_embedding_api(text)

    # 本地模式
    return _get_embedding_local(text, model_params["local_path"])


def _embedding_with_retry(client, model_name: str, batch: List[str], max_retries: int = 3):
    """
    调用 Embedding API 并自动重试（指数退避）。
    仅在可重试的异常（超时/网络/限流/服务端错误）上重试，最多 max_retries 次。
    """
    from openai import APIError, APITimeoutError, RateLimitError, APIConnectionError
    import time

    for attempt in range(max_retries):
        try:
            return client.embeddings.create(model=model_name, input=batch)
        except (APITimeoutError, APIConnectionError, RateLimitError) as e:
            if attempt == max_retries - 1:
                raise
            delay = 2 ** attempt  # 1, 2, 4 秒
            logger.warning(
                f"Embedding API 临时错误 (第 {attempt + 1}/{max_retries} 次): {e}，"
                f"{delay} 秒后重试"
            )
            time.sleep(delay)
        except APIError as e:
            # 仅在服务端错误 (5xx) 时重试，客户端错误 (4xx) 不重试
            if e.status_code and 500 <= e.status_code < 600 and attempt < max_retries - 1:
                delay = 2 ** attempt
                logger.warning(
                    f"Embedding API 服务端错误 (第 {attempt + 1}/{max_retries} 次): {e}，"
                    f"{delay} 秒后重试"
                )
                time.sleep(delay)
            else:
                raise


def _get_embedding_api(texts: List[str]) -> np.ndarray:
    """通过 DashScope API 获取 embedding（自动按 batch_size=10 分批，带重试）"""
    model_name = settings.rag.embedding_model
    client = _get_lazy_llm_client()
    batch_size = 10

    logger.info(f"API Embedding: {len(texts)} 条文本，模型：{model_name}，分批大小={batch_size}")

    all_vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = _embedding_with_retry(client, model_name, batch)
        vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        all_vectors.extend(vectors)

    return np.array(all_vectors, dtype=np.float32)


def _get_embedding_local(texts: List[str], model_path: str) -> np.ndarray:
    """通过本地 Sentence-Transformer 模型获取 embedding"""
    global _embedding_model

    if _embedding_model is None:
        logger.info(f"加载本地 Embedding 模型：{model_path}")
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(model_path)
        logger.info("本地 Embedding 模型加载完成")

    vectors = _embedding_model.encode(texts, normalize_embeddings=True)
    return vectors


def get_rerank_scores(text_pairs: List[List[str]]) -> np.ndarray:
    """
    调用 DashScope gte-rerank API 进行精排。

    请求格式：
        POST https://dashscope.aliyuncs.com/api/v1/services/ranker/gte-rerank/hybrid
        {"model": "gte-rerank", "query": "…", "documents": ["…", …], "top_n": N}

    失败时返回空数组，由调用方降级到 RRF 排序，不影响主流程。
    """
    if not text_pairs:
        return np.array([])

    api_key = settings.rag.llm_api_key
    if not api_key:
        logger.warning("Reranker: API Key 未配置，跳过")
        return np.array([])

    query = text_pairs[0][0]
    documents = [pair[1] for pair in text_pairs]

    import httpx

    url = "https://dashscope.aliyuncs.com/api/v1/services/ranker/gte-rerank/hybrid"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.rag.rerank_model or "gte-rerank",
        "query": query,
        "documents": documents,
        "top_n": len(documents),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        scores = np.zeros(len(documents), dtype=np.float32)
        for item in data["output"]["results"]:
            scores[item["index"]] = item["relevance_score"]

        logger.info(f"Reranker 完成: {len(documents)} 个文档块已打分")
        return scores

    except Exception as e:
        logger.error(f"Reranker API 调用失败，降级至 RRF 排序: {e}")
        return np.array([])
