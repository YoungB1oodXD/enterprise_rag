"""
Rerank 效果评估脚本

评估目标：
  1. Rerank 前后的 top-K 精度对比
  2. 不同 confidence_threshold 对保留率和精度的影响
  3. Rerank 是否将相关结果排到更靠前的位置

用法：
  python tests/evaluate_rerank.py \
      --dataset dataset/eval_dataset_ip_customs_answerable_27.json \
      --knowledge_id 1 \
      --output tests/result_rerank.json

备注：
  需要先在 config.yaml 中启用 Rerank：
    rag:
      use_rerank: true
      rerank_model: "BAAI/bge-reranker-v2-m3"  # 或你的 reranker 路径
"""
import json
import re
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.es_client import es
from app.core.logger import get_logger
from app.models.model_manager import get_embedding, get_rerank_scores

logger = get_logger(__name__)


# ================================================================
# 工具函数
# ================================================================

def _extract_article_numbers(breadcrumb: str):
    parts = breadcrumb.split(" > ")
    result = []
    for part in parts:
        m = re.search(r'第[一二三四五六七八九十\d]+条', part)
        if m:
            result.append(m.group())
    return result


def _is_relevant(chunk, expected_articles):
    breadcrumb = chunk.get("breadcrumb", "")
    chunk_articles = _extract_article_numbers(breadcrumb)
    return any(art in chunk_articles for art in expected_articles)


def compute_precision(ranked_docs, expected_articles, k=5):
    top_k = ranked_docs[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for d in top_k if _is_relevant(d, expected_articles))
    return hits / k


# ================================================================
# 搜索
# ================================================================

def _normalize_hits(hits):
    result = []
    for hit in hits:
        doc = dict(hit.get("_source", {}))
        doc["_id"] = hit["_id"]
        result.append(doc)
    return result


def search_bm25(query, knowledge_id, top_k=50):
    index_name = settings.es.index_chunk_info
    q = {
        "bool": {
            "must": [{"match": {"chunk_content": query}}],
            "filter": [{"term": {"knowledge_id": knowledge_id}}],
        }
    }
    res = es.search(index=index_name, query=q, size=top_k)
    return _normalize_hits(res["hits"]["hits"])


def search_vector(query, knowledge_id, top_k=50):
    index_name = settings.es.index_chunk_info
    qv = get_embedding(query)[0].tolist()
    knn = {
        "field": "embedding_vector",
        "query_vector": qv,
        "k": top_k,
        "num_candidates": max(top_k * 2, 100),
        "filter": {"term": {"knowledge_id": knowledge_id}},
    }
    res = es.search(index=index_name, knn=knn, size=top_k)
    return _normalize_hits(res["hits"]["hits"])


def rrf_fuse(results_list, k=60):
    fused = {}
    doc_map = {}
    for results in results_list:
        for rank, hit in enumerate(results):
            doc_id = hit["_id"]
            if doc_id not in fused:
                fused[doc_id] = 0
                doc_map[doc_id] = hit
            fused[doc_id] += 1 / (k + rank + 1)
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    result = []
    for doc_id, score in ranked:
        doc = doc_map[doc_id]
        doc["_id"] = doc_id
        doc["rrf_score"] = score
        result.append(doc)
    return result


def search_hybrid(query, knowledge_id, top_k=50, rrf_k=60):
    bm25_hits = search_bm25(query, knowledge_id, top_k=top_k)
    vector_hits = search_vector(query, knowledge_id, top_k=top_k)
    return rrf_fuse([bm25_hits, vector_hits], k=rrf_k)


# ================================================================
# 主流程
# ================================================================

def evaluate_rerank(
    dataset_path: str,
    knowledge_id: int,
    output_path: str,
    top_k: int = 50,
    rrf_k: int = 60,
    thresholds: list = None,
):
    if thresholds is None:
        thresholds = [0.0, 0.1, 0.3, 0.5]

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    # 检查是否启用 Rerank
    if not settings.rag.use_rerank:
        logger.warning("=" * 60)
        logger.warning("当前 config.yaml 中 use_rerank: false，Rerank 未启用。")
        logger.warning("如需评估 Rerank 效果，请先配置并启用 Rerank 模型。")
        logger.warning("将跳过 Rerank 部分，仅输出 Hybrid 基线结果。")
        logger.warning("=" * 60)
        rerank_available = False
    else:
        rerank_available = True
        logger.info(f"Rerank 已启用，模型: {settings.rag.rerank_model}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    samples = dataset["samples"]
    n = len(samples)
    logger.info(f"加载评估集: {dataset_path} → {n} 条")

    # 统计容器
    hybrid_precisions = {k: [] for k in [1, 3, 5, 10]}
    rerank_precisions = {k: [] for k in [1, 3, 5, 10]} if rerank_available else None
    threshold_stats = {t: {"precision": {k: [] for k in [1, 3, 5, 10]},
                           "retained": []} for t in thresholds} if rerank_available else None

    per_sample_results = []

    for i, sample in enumerate(samples):
        qid = sample.get("id", i + 1)
        question = sample["question"]
        expected = sample.get("source_articles", [])

        logger.info(f"[{i + 1}/{n}] ID={qid} 查询: {question[:40]}...")

        # 1. Hybrid 基线
        hybrid_docs = search_hybrid(question, knowledge_id, top_k=top_k, rrf_k=rrf_k)
        for k in [1, 3, 5, 10]:
            hybrid_precisions[k].append(compute_precision(hybrid_docs, expected, k=k))

        sample_result = {
            "id": qid,
            "question": question,
            "expected_articles": expected,
            "hybrid_precision": {k: compute_precision(hybrid_docs, expected, k=k) for k in [1, 3, 5, 10]},
        }

        if rerank_available:
            # 2. Rerank 精排
            pairs = [[question, d["chunk_content"]] for d in hybrid_docs]
            scores = get_rerank_scores(pairs)
            for idx, doc in enumerate(hybrid_docs):
                doc["rerank_score"] = float(scores[idx])
            reranked = sorted(hybrid_docs, key=lambda x: x["rerank_score"], reverse=True)

            for k in [1, 3, 5, 10]:
                rerank_precisions[k].append(compute_precision(reranked, expected, k=k))

            # 3. 不同 threshold 的影响
            for t in thresholds:
                filtered = [d for d in reranked if d["rerank_score"] > t]
                threshold_stats[t]["retained"].append(len(filtered) / max(len(reranked), 1))
                for k in [1, 3, 5, 10]:
                    threshold_stats[t]["precision"][k].append(
                        compute_precision(filtered, expected, k=k) if len(filtered) >= k else 0.0
                    )

            sample_result["rerank_precision"] = {
                k: compute_precision(reranked, expected, k=k) for k in [1, 3, 5, 10]
            }
            sample_result["rerank_scores"] = [d.get("rerank_score", 0) for d in reranked[:10]]

        per_sample_results.append(sample_result)

    # 汇总
    print("\n" + "=" * 80)
    print(f"  Rerank 效果评估 | 数据集: {os.path.basename(dataset_path)} | {n} 条")
    print("=" * 80)

    if rerank_available:
        print(f"{'K':<10} {'Hybrid Precision':<20} {'+Rerank Precision':<20} {'提升':<15}")
        print("-" * 65)
        for k in [1, 3, 5, 10]:
            hp = round(sum(hybrid_precisions[k]) / n, 4)
            rp = round(sum(rerank_precisions[k]) / n, 4)
            delta = rp - hp
            print(f"{k:<10} {hp:<20.4f} {rp:<20.4f} {'+' if delta > 0 else ''}{delta:.4f}")

        print("\n--- confidence_threshold 影响 ---")
        print(f"{'Threshold':<15} {'Prec@5':<15} {'保留率':<15}")
        print("-" * 45)
        for t in thresholds:
            avg_p = round(sum(threshold_stats[t]["precision"][5]) / n, 4)
            avg_r = round(sum(threshold_stats[t]["retained"]) / n, 4)
            print(f"{t:<15} {avg_p:<15.4f} {avg_r:<15.4f}")
    else:
        print("Hybrid Precision（Rerank 未启用，仅输出基线）：")
        for k in [1, 3, 5, 10]:
            hp = round(sum(hybrid_precisions[k]) / n, 4)
            print(f"  Precision@{k}: {hp:.4f}")
        print("\n提示：启用 Rerank 后重跑即可对比。")

    print("=" * 80)

    # 保存结果
    result = {
        "dataset": dataset_path,
        "n_samples": n,
        "knowledge_id": knowledge_id,
        "rerank_available": rerank_available,
        "hybrid_avg_precision": {
            str(k): round(sum(hybrid_precisions[k]) / n, 4) for k in [1, 3, 5, 10]
        },
    }
    if rerank_available:
        result["rerank_avg_precision"] = {
            str(k): round(sum(rerank_precisions[k]) / n, 4) for k in [1, 3, 5, 10]
        }
        result["threshold_impact"] = {}
        for t in thresholds:
            result["threshold_impact"][str(t)] = {
                "precision@5": round(sum(threshold_stats[t]["precision"][5]) / n, 4),
                "retention_rate": round(sum(threshold_stats[t]["retained"]) / n, 4),
            }

    result["per_sample"] = per_sample_results

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存: {output_path}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rerank 效果评估")
    parser.add_argument("--dataset", default="dataset/eval_dataset_ip_customs_answerable_27.json")
    parser.add_argument("--knowledge_id", type=int, default=1)
    parser.add_argument("--output", default="tests/result_rerank.json")
    parser.add_argument("--top_k", type=int, default=50)
    parser.add_argument("--rrf_k", type=int, default=60)
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.0, 0.1, 0.3, 0.5])
    args = parser.parse_args()

    evaluate_rerank(
        dataset_path=args.dataset,
        knowledge_id=args.knowledge_id,
        output_path=args.output,
        top_k=args.top_k,
        rrf_k=args.rrf_k,
        thresholds=args.thresholds,
    )
