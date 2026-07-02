# app/retrieval/searcher.py

from typing import List, Dict, Any
from app.core.es_client import es
from app.core.config import settings
from app.core.logger import get_logger
from app.models.model_manager import get_embedding, get_rerank_scores
from app.utils.cache import LRUCache

logger = get_logger(__name__)

# 向量缓存：相同 query 在 TTL 内复用 embedding，避免重复调用模型
embedding_cache = LRUCache(capacity=500, ttl=3600)


def reciprocal_rank_fusion(search_results_list: List[List[Dict]], k: int = 60) -> List[Dict]:
    """
    RRF 融合算法
    :param search_results_list: 多个检索渠道的结果列表
    :return: 融合后重新排序的结果列表
    """
    fused_scores = {}
    doc_map = {}  # 用于保存文档的具体内容，方便后续提取

    for results in search_results_list:
        for rank, hit in enumerate(results):
            doc_id = hit["_id"]
            if doc_id not in fused_scores:
                fused_scores[doc_id] = 0
                doc_map[doc_id] = hit["_source"]

            fused_scores[doc_id] += 1 / (k + rank + 1)

    # 排序
    reranked_results = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)

    # 组装返回格式
    final_docs = []
    for doc_id, score in reranked_results:
        doc_data = doc_map[doc_id]
        doc_data["_id"] = doc_id
        doc_data["rrf_score"] = score
        final_docs.append(doc_data)

    return final_docs


def hybrid_search(query: str, knowledge_id: int) -> List[Dict[str, Any]]:
    """
    执行 ES 混合检索 (BM25 + 向量) -> RRF 融合 -> Rerank 精排
    """
    logger.info(f"开始混合检索，查询: '{query}', 知识库ID: {knowledge_id}")
    index_name = settings.es.index_chunk_info

    # 1. BM25 全文检索 (加上 knowledge_id 过滤)
    bm25_query = {
        "bool": {
            "must": [{"match": {"chunk_content": query}}],
            "filter": [{"term": {"knowledge_id": knowledge_id}}]
        }
    }
    try:
        bm25_res = es.search(index=index_name, query=bm25_query, size=settings.rag.bm25_top_k)
        bm25_hits = bm25_res["hits"]["hits"]
    except Exception as e:
        logger.error(f"BM25 检索失败: {e}")
        bm25_hits = []

    # 2. 向量检索 (调用 model_manager 获取向量，优先使用缓存)
    try:
        cache_key = f"embed:{query}"
        cached = embedding_cache.get(cache_key)
        if cached is not None:
            query_vector = cached
            logger.debug(f"向量缓存命中: '{query[:50]}'")
        else:
            query_vector = get_embedding(query)[0].tolist()
            embedding_cache.set(cache_key, query_vector)
        knn_query = {
            "field": "embedding_vector",
            "query_vector": query_vector,
            "k": settings.rag.vector_top_k,
            "num_candidates": 50,
            "filter": {"term": {"knowledge_id": knowledge_id}}
        }
        knn_res = es.search(index=index_name, knn=knn_query, size=settings.rag.vector_top_k)
        knn_hits = knn_res["hits"]["hits"]
    except Exception as e:
        logger.error(f"向量检索失败: {e}")
        knn_hits = []

    # 3. RRF 融合
    fused_docs = reciprocal_rank_fusion([bm25_hits, knn_hits], k=settings.rag.rrf_k)
    logger.info(f"RRF 融合完成，共召回 {len(fused_docs)} 个文档块")

    # 如果配置中不使用 Rerank，直接返回
    if not settings.rag.use_rerank or not fused_docs:
        return fused_docs[:settings.rag.rerank_top_k]

    # 4. Rerank 精排
    logger.info("开始 Rerank 精排...")
    pairs = [[query, doc["chunk_content"]] for doc in fused_docs]

    # 调用 model_manager 进行打分
    scores = get_rerank_scores(pairs)

    # 如果 Reranker 返回空（API 失败/未配置），降级使用 RRF 排序
    if len(scores) == 0:
        logger.warning("Reranker 返回空分数，降级使用 RRF 排序")
        return fused_docs[:settings.rag.rerank_top_k]

    # 将分数更新回文档，并按精排分数重新排序
    for i, doc in enumerate(fused_docs):
        doc["rerank_score"] = float(scores[i])

    reranked_docs = sorted(fused_docs, key=lambda x: x["rerank_score"], reverse=True)

    # P0: 取 Top K 并过滤掉分数低于阈值的辣鸡文档
    passed = []
    for doc in reranked_docs[:settings.rag.rerank_top_k]:
        if doc["rerank_score"] > settings.rag.confidence_threshold:
            passed.append(doc)

    # P0: 保底 — 即使低于阈值也至少保留 min_rerank_top_k 个，
    # 避免场景题等低分但相关问题被全部过滤导致 LLM 无法回答
    min_top_k = settings.rag.min_rerank_top_k
    if len(passed) < min_top_k and reranked_docs:
        existing_ids = {d["_id"] for d in passed}
        for doc in reranked_docs:
            if doc["_id"] not in existing_ids:
                passed.append(doc)
                existing_ids.add(doc["_id"])
                if len(passed) >= min_top_k:
                    break
        logger.info(
            f"保底策略：低于阈值({settings.rag.confidence_threshold})，"
            f"从 {len(reranked_docs)} 个候选中补全到 {len(passed)} 个 chunk"
        )

    # P1: 零来源降级 — 若 rerank 后仍无结果（阈值过高或 reranker 异常），
    # 直接拿 RRF 融合的前 N 个结果兜底
    if not passed and fused_docs:
        logger.warning(
            f"Reranker 全量过滤，降级使用 RRF 前 {settings.rag.rerank_top_k} 个结果"
        )
        passed = fused_docs[:settings.rag.rerank_top_k]
        for doc in passed:
            doc["rerank_score"] = doc.get("rerank_score", 0.0)
            doc["fallback_from_rerank"] = True

    logger.info(f"Rerank 完成，最终保留 {len(passed)} 个高质量文档块")
    return passed