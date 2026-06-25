"""
Top-K 对比评估脚本：对比不同 top_k 下的检索+生成质量。

用法：
  # 仅评估检索
  python scripts/evaluate_with_topk.py --knowledge_id 1 --dataset scripts/eval_dataset.json --output scripts/result.json --skip_llm

  # 端到端评估（含 LLM 生成）
  python scripts/evaluate_with_topk.py --knowledge_id 1 --dataset scripts/eval_dataset.json --output scripts/result.json
"""
import json
import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.logger import get_logger
from app.services.qa_service import chat_with_knowledge_base

logger = get_logger(__name__)


def load_dataset(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["samples"]


def is_rejection(answer: str) -> bool:
    """检测回答是否为拒答（未找到相关内容）。"""
    rejection_phrases = [
        "抱歉", "未找到", "无法回答", "没有检索到", "没有找到",
        "不在知识库", "无法准确回答", "未提及",
    ]
    return any(p in answer for p in rejection_phrases)


def evaluate_retrieval(samples: list, knowledge_id: int, top_ks: list) -> dict:
    """仅评估检索质量：对不同 top_k 计算命中率。"""
    from app.retrieval.searcher import hybrid_search

    results = {}
    for k in top_ks:
        hit_count = 0
        total = 0
        for sample in samples:
            articles = sample.get("source_articles", [])
            if not articles:
                continue
            total += 1
            docs = hybrid_search(sample["question"], knowledge_id)[:k]
            for doc in docs:
                breadcrumb = doc.get("breadcrumb", "")
                if any(art in breadcrumb for art in articles):
                    hit_count += 1
                    break
        results[k] = round(hit_count / total, 4) if total else 0
        logger.info(f"  Top-{k} HitRate: {results[k]}")
    return results


def evaluate_end2end(samples: list, knowledge_id: int) -> list:
    """端到端评估：检索 + LLM 生成。"""
    results = []
    for sample in samples:
        question = sample["question"]
        expected = sample.get("reference_answer", "")
        logger.info(f"  评估: {question[:50]}...")

        answer, sources = chat_with_knowledge_base(knowledge_id, question, [])

        result = {
            "id": sample["id"],
            "question": question,
            "expected": expected,
            "answer": answer,
            "source_count": len(sources),
            "is_rejection": is_rejection(answer),
        }

        if expected:
            # 简单关键词召回率（作为基础指标）
            recall = sum(1 for w in expected.split("，") if w[:4] in answer)
            result["keyword_recall"] = round(recall / max(len(expected.split("，")), 1), 4)

        results.append(result)
        logger.info(f"    回答长度: {len(answer)}, 拒答: {result['is_rejection']}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Top-K 对比评估")
    parser.add_argument("--knowledge_id", type=int, required=True)
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--output", type=str, default="scripts/result.json")
    parser.add_argument("--skip_llm", action="store_true", help="跳过 LLM 生成，仅评估检索")
    args = parser.parse_args()

    samples = load_dataset(args.dataset)
    logger.info(f"加载数据集: {len(samples)} 条")

    output = {}
    top_ks = [1, 3, 5, 10]

    # 检索评估
    output["retrieval"] = evaluate_retrieval(samples, args.knowledge_id, top_ks)

    # 端到端评估
    if not args.skip_llm:
        output["end2end"] = evaluate_end2end(samples, args.knowledge_id)
        rejection_rate = sum(1 for r in output["end2end"] if r["is_rejection"]) / len(output["end2end"])
        output["rejection_rate"] = round(rejection_rate, 4)
        logger.info(f"拒答率: {output['rejection_rate']}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存到 {args.output}")


if __name__ == "__main__":
    main()
