"""
检索质量评估脚本：BM25 / Vector / Hybrid 三种模式对比，输出 HitRate / MRR / Precision。

用法：
  python scripts/evaluate_retrieval_only.py --knowledge_id 1 --dataset scripts/eval_dataset.json --output scripts/result.json
"""
import json
import os
import re
import sys
import argparse
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.es_client import es
from app.core.logger import get_logger
from app.models.model_manager import get_embedding

logger = get_logger(__name__)


def _extract_article_numbers(breadcrumb: str) -> List[str]:
    parts = breadcrumb.split(" > ")
    result = []
    for part in parts:
        m = re.search(r'第[一二三四五六七八九十\d]+条', part)
        if m:
            result.append(m.group())
    return result


def _is_chunk_relevant(chunk, expected_articles: List[str]) -> bool:
    breadcrumb = chunk.get("breadcrumb", "")
    chunk_articles = _extract_article_numbers(breadcrumb)
    return any(art in chunk_articles for art in expected_articles)


def search_bm25(query: str, knowledge_id: int, top_k: int = 50) -> list:
    bm25_query = {
        "bool": {
            "must": [{"match": {"chunk_content": query}}],
            "filter": [{"term": {"knowledge_id": knowledge_id}}],
        }
    }
    res = es.search(index=settings.es.index_chunk_info, query=bm25_query, size=top_k)
    return res["hits"]["hits"]


def search_vector(query: str, knowledge_id: int, top_k: int = 50) -> list:
    query_vector = get_embedding(query)[0].tolist()
    knn = {
        "field": "embedding_vector",
        "query_vector": query_vector,
        "k": top_k,
        "num_candidates": 50,
        "filter": {"term": {"knowledge_id": knowledge_id}},
    }
    res = es.search(index=settings.es.index_chunk_info, knn=knn, size=top_k)
    return res["hits"]["hits"]


def rrf_fuse(results_list: list, k: int = 60) -> list:
    fused = {}
    docs = {}
    for results in results_list:
        for rank, hit in enumerate(results):
            doc_id = hit["_id"]
            source = hit["_source"]
            if doc_id not in fused:
                fused[doc_id] = 0
                docs[doc_id] = source
            fused[doc_id] += 1 / (k + rank + 1)
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    final = []
    for doc_id, score in ranked:
        d = docs[doc_id]
        d["_id"] = doc_id
        d["rrf_score"] = score
        final.append(d)
    return final


def search_hybrid(query: str, knowledge_id: int, bm25_top_k=50, vector_top_k=50, rrf_k=60) -> list:
    bm25 = search_bm25(query, knowledge_id, bm25_top_k)
    vec = search_vector(query, knowledge_id, vector_top_k)
    return rrf_fuse([bm25, vec], k=rrf_k)


def compute_metrics(ranked_docs: list, expected_articles: List[str], k_list: List[int]):
    hit_rate = {}
    mrr = {}
    precision = {}
    recall = {}
    total_relevant = max(len(expected_articles), 1)

    first_relevant_rank = None
    for rank, doc in enumerate(ranked_docs, 1):
        if _is_chunk_relevant(doc, expected_articles):
            if first_relevant_rank is None:
                first_relevant_rank = rank
            break

    for k in k_list:
        top_k = ranked_docs[:k]
        relevant = sum(1 for d in top_k if _is_chunk_relevant(d, expected_articles))
        hit_rate[k] = 1 if relevant > 0 else 0
        mrr[k] = 1.0 / first_relevant_rank if first_relevant_rank and first_relevant_rank <= k else 0
        precision[k] = relevant / k
        recall[k] = relevant / total_relevant

    return {"hit_rate": hit_rate, "mrr": mrr, "precision": precision, "recall": recall, "first_rank": first_relevant_rank}


def main():
    parser = argparse.ArgumentParser(description="检索质量评估")
    parser.add_argument("--knowledge_id", type=int, required=True)
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--output", type=str, default="scripts/result.json")
    args = parser.parse_args()

    with open(args.dataset, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    samples = dataset["samples"]
    k_list = [1, 3, 5, 10]
    modes = {
        "bm25": lambda q: search_bm25(q, args.knowledge_id),
        "vector": lambda q: search_vector(q, args.knowledge_id),
        "hybrid": lambda q: search_hybrid(q, args.knowledge_id),
    }

    results = {}
    for mode_name, search_fn in modes.items():
        logger.info(f"评估模式: {mode_name}")
        all_metrics = []
        for sample in samples:
            articles = sample.get("source_articles", [])
            if not articles:
                continue
            docs = search_fn(sample["question"])
            metrics = compute_metrics(docs, articles, k_list)
            all_metrics.append(metrics)

        avg = {}
        for metric_name in ["hit_rate", "mrr", "precision", "recall"]:
            avg[metric_name] = {}
            for k in k_list:
                values = [m[metric_name][k] for m in all_metrics]
                avg[metric_name][k] = round(sum(values) / len(values), 4) if values else 0
        results[mode_name] = avg
        logger.info(f"  HitRate@5: {avg['hit_rate'][5]}, MRR@5: {avg['mrr'][5]}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存到 {args.output}")


if __name__ == "__main__":
    main()
