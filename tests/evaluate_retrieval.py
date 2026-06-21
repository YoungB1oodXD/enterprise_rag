"""
检索质量离线评估脚本

评估目标：
  1. BM25-only、Vector-only、Hybrid(RRF) 三种模式对比
  2. HitRate@K / MRR@K / Precision@K / Recall@K

用法：
  python tests/evaluate_retrieval.py \
      --dataset dataset/eval_dataset_ip_customs_answerable_27.json \
      --knowledge_id 1 \
      --output tests/result_retrieval.json

依赖：
  pip install numpy
"""
import json
import re
import sys
import time
import argparse
import numpy as np
from typing import List, Dict, Any, Optional

# ── 确保能找到 app 模块（从项目根目录） ─────────────────────────
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.es_client import es
from app.core.logger import get_logger
from app.models.model_manager import get_embedding

logger = get_logger(__name__)


# ================================================================
# 工具函数
# ================================================================

def _extract_article_numbers(breadcrumb: str) -> List[str]:
    """从面包屑中提取条号，如 '第二章 > 第十条 ...' → ['第十条']"""
    parts = breadcrumb.split(" > ")
    result = []
    for part in parts:
        m = re.search(r'第[一二三四五六七八九十\d]+条', part)
        if m:
            result.append(m.group())
    return result


def _is_chunk_relevant(chunk: Dict, expected_articles: List[str]) -> bool:
    """判断一个 chunk 是否与问题相关（通过条号匹配）"""
    breadcrumb = chunk.get("breadcrumb", "")
    chunk_articles = _extract_article_numbers(breadcrumb)
    return any(art in chunk_articles for art in expected_articles)


# ================================================================
# 搜索包装器（三种模式）
# ================================================================

def _normalize_hits(hits: List[Dict]) -> List[Dict]:
    """将 ES 原始 hit 转为一层 dict（_source 展开，_id 并入）"""
    result = []
    for hit in hits:
        doc = dict(hit.get("_source", {}))
        doc["_id"] = hit["_id"]
        result.append(doc)
    return result


def search_bm25(query: str, knowledge_id: int, top_k: int = 50) -> List[Dict]:
    """BM25 全文检索"""
    index_name = settings.es.index_chunk_info
    bm25_query = {
        "bool": {
            "must": [{"match": {"chunk_content": query}}],
            "filter": [{"term": {"knowledge_id": knowledge_id}}],
        }
    }
    res = es.search(index=index_name, query=bm25_query, size=top_k)
    return _normalize_hits(res["hits"]["hits"])


def search_vector(query: str, knowledge_id: int, top_k: int = 50) -> List[Dict]:
    """向量检索"""
    index_name = settings.es.index_chunk_info
    query_vector = get_embedding(query)[0].tolist()
    knn_query = {
        "field": "embedding_vector",
        "query_vector": query_vector,
        "k": top_k,
        "num_candidates": max(top_k * 2, 100),
        "filter": {"term": {"knowledge_id": knowledge_id}},
    }
    res = es.search(index=index_name, knn=knn_query, size=top_k)
    return _normalize_hits(res["hits"]["hits"])


def rrf_fuse(results_list: List[List[Dict]], k: int = 60) -> List[Dict]:
    """RRF 融合"""
    fused = {}
    doc_map = {}
    for results in results_list:
        for rank, hit in enumerate(results):
            doc_id = hit["_id"]
            if doc_id not in fused:
                fused[doc_id] = 0
                doc_map[doc_id] = hit  # hit 已是一层 dict（_normalize_hits 处理过）
            fused[doc_id] += 1 / (k + rank + 1)
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    result = []
    for doc_id, score in ranked:
        doc = doc_map[doc_id]
        doc["_id"] = doc_id
        doc["rrf_score"] = score
        result.append(doc)
    return result


def search_hybrid(query: str, knowledge_id: int,
                  bm25_top_k: int = 50, vector_top_k: int = 50,
                  rrf_k: int = 60) -> List[Dict]:
    """混合检索: BM25 + Vector → RRF"""
    bm25_hits = search_bm25(query, knowledge_id, top_k=bm25_top_k)
    vector_hits = search_vector(query, knowledge_id, top_k=vector_top_k)
    return rrf_fuse([bm25_hits, vector_hits], k=rrf_k)


# ================================================================
# 评估指标计算
# ================================================================

def compute_metrics(
    ranked_docs: List[Dict],
    expected_articles: List[str],
    all_relevant_count: Optional[int] = None,
    k_list: List[int] = None,
) -> Dict:
    """
    对单条问题，计算各 K 下的指标。

    参数:
      ranked_docs:         排序后的检索结果（按相关性从高到低）
      expected_articles:   期望命中的条号列表，如 ["第十条", "第十一条"]
      all_relevant_count:  总相关文档数（Recall 需要）。None 时取搜索结果中实际匹配数

    返回:
      { "hit_rate": {1:..., 3:..., ...}, "mrr": ..., "precision": {...}, "recall": {...} }
    """
    if k_list is None:
        k_list = [1, 3, 5, 10]

    # 判断每个文档是否相关
    relevance = [_is_chunk_relevant(d, expected_articles) for d in ranked_docs]
    found_positions = [i + 1 for i, r in enumerate(relevance) if r]

    total_relevant = all_relevant_count or sum(relevance)
    first_rank = found_positions[0] if found_positions else None

    metrics = {}

    # HitRate@K / Precision@K / Recall@K
    hit_rates = {}
    precisions = {}
    recalls = {}
    for k in k_list:
        top_k_rel = relevance[:k]
        hits = sum(top_k_rel)
        hit_rates[k] = 1.0 if hits > 0 else 0.0
        precisions[k] = hits / k if k > 0 else 0.0
        recalls[k] = hits / total_relevant if total_relevant > 0 else 0.0

    # MRR@K (用 K=10)
    mrr = (1.0 / first_rank) if first_rank and first_rank <= 10 else 0.0

    return {
        "hit_rate": hit_rates,
        "mrr": mrr,
        "precision": precisions,
        "recall": recalls,
        "first_rank": first_rank,
    }


# ================================================================
# 主流程
# ================================================================

def evaluate_retrieval(
    dataset_path: str,
    knowledge_id: int,
    output_path: str,
    modes: List[str] = None,
    k_list: List[int] = None,
    bm25_top_k: int = 50,
    vector_top_k: int = 50,
    rrf_k: int = 60,
) -> Dict:
    """主评估流程"""
    if modes is None:
        modes = ["bm25", "vector", "hybrid"]
    if k_list is None:
        k_list = [1, 3, 5, 10]

    # 加载数据集
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    samples = dataset["samples"]
    logger.info(f"加载评估集: {dataset_path} → {len(samples)} 条")

    # 初始化各模式的累计指标
    all_results = {mode: [] for mode in modes}
    summary = {
        mode: {
            "hit_rate": {k: 0.0 for k in k_list},
            "mrr": 0.0,
            "precision": {k: 0.0 for k in k_list},
            "recall": {k: 0.0 for k in k_list},
        }
        for mode in modes
    }

    n = len(samples)
    for i, sample in enumerate(samples):
        qid = sample.get("id", i + 1)
        question = sample["question"]
        expected = sample.get("source_articles", [])

        logger.info(f"[{i + 1}/{n}] ID={qid} 模式={modes} 查询: {question[:40]}...")

        for mode in modes:
            if mode == "bm25":
                docs = search_bm25(question, knowledge_id, top_k=bm25_top_k)
            elif mode == "vector":
                docs = search_vector(question, knowledge_id, top_k=vector_top_k)
            elif mode == "hybrid":
                docs = search_hybrid(question, knowledge_id,
                                     bm25_top_k=bm25_top_k,
                                     vector_top_k=vector_top_k,
                                     rrf_k=rrf_k)
            else:
                raise ValueError(f"未知模式: {mode}")

            metrics = compute_metrics(docs, expected, k_list=k_list)
            all_results[mode].append({
                "id": qid,
                "question": question,
                "expected_articles": expected,
                "first_rank": metrics["first_rank"],
                "hit_rate": metrics["hit_rate"],
                "mrr": metrics["mrr"],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
            })

            # 累加
            for k in k_list:
                summary[mode]["hit_rate"][k] += metrics["hit_rate"][k]
                summary[mode]["precision"][k] += metrics["precision"][k]
                summary[mode]["recall"][k] += metrics["recall"][k]
            summary[mode]["mrr"] += metrics["mrr"]

    # 求平均
    for mode in modes:
        for k in k_list:
            summary[mode]["hit_rate"][k] = round(summary[mode]["hit_rate"][k] / n, 4)
            summary[mode]["precision"][k] = round(summary[mode]["precision"][k] / n, 4)
            summary[mode]["recall"][k] = round(summary[mode]["recall"][k] / n, 4)
        summary[mode]["mrr"] = round(summary[mode]["mrr"] / n, 4)

    # 打印结果表格
    print("\n" + "=" * 80)
    print(f"  检索质量评估结果 | 数据集: {os.path.basename(dataset_path)} | {n} 条")
    print("=" * 80)
    header = f"{'指标':<20}"
    for mode in modes:
        header += f"  {mode:<15}"
    print(header)
    print("-" * 80)

    for k in k_list:
        row = f"HitRate@{k:<3}           "
        for mode in modes:
            row += f"  {summary[mode]['hit_rate'][k]:<15.4f}"
        print(row)

    row = f"{'MRR@10':<20}"
    for mode in modes:
        row += f"  {summary[mode]['mrr']:<15.4f}"
    print(row)
    print("-" * 80)

    for k in k_list:
        row = f"Precision@{k:<3}         "
        for mode in modes:
            row += f"  {summary[mode]['precision'][k]:<15.4f}"
        print(row)
    print("-" * 80)

    for k in k_list:
        row = f"Recall@{k:<3}            "
        for mode in modes:
            row += f"  {summary[mode]['recall'][k]:<15.4f}"
        print(row)

    print("=" * 80)

    # 组装完整输出
    result = {
        "dataset": dataset_path,
        "n_samples": n,
        "knowledge_id": knowledge_id,
        "parameters": {
            "bm25_top_k": bm25_top_k,
            "vector_top_k": vector_top_k,
            "rrf_k": rrf_k,
        },
        "summary": summary,
        "per_sample": all_results,
    }

    # 保存 JSON
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存: {output_path}")

    return result


# ================================================================
# CLI 入口
# ================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检索质量离线评估")
    parser.add_argument("--dataset", default="dataset/eval_dataset_ip_customs_answerable_27.json",
                        help="评估集 JSON 路径")
    parser.add_argument("--knowledge_id", type=int, default=1,
                        help="知识库 ID")
    parser.add_argument("--output", default="tests/result_retrieval.json",
                        help="输出结果路径")
    parser.add_argument("--modes", nargs="+", default=["bm25", "vector", "hybrid"],
                        choices=["bm25", "vector", "hybrid"],
                        help="要对比的检索模式")
    parser.add_argument("--bm25_top_k", type=int, default=50)
    parser.add_argument("--vector_top_k", type=int, default=50)
    parser.add_argument("--rrf_k", type=int, default=60)
    args = parser.parse_args()

    evaluate_retrieval(
        dataset_path=args.dataset,
        knowledge_id=args.knowledge_id,
        output_path=args.output,
        modes=args.modes,
        bm25_top_k=args.bm25_top_k,
        vector_top_k=args.vector_top_k,
        rrf_k=args.rrf_k,
    )
