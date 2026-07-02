"""
RAGAS 评估脚本 — 一键跑 RAGAS 指标

用法：
  # 跑 3 条验证链路
  python scripts/run_ragas_eval.py --dataset dataset/eval_dataset_ip_customs_answerable_27.json --knowledge-id 1 --limit 3

  # 跑全量 27 条
  python scripts/run_ragas_eval.py --dataset dataset/eval_dataset_ip_customs_answerable_27.json --knowledge-id 1

  # 跑平衡集 30 条并保存结果
  python scripts/run_ragas_eval.py \
    --dataset dataset/eval_dataset_ip_customs_balanced_30.json \
    --knowledge-id 1 \
    --output eval_results/ragas_result.json

依赖:
  pip install -r requirements-eval.txt
  ES 运行中且有对应知识库的数据
"""
import argparse
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.logger import get_logger
from app.services.qa_service import chat_with_knowledge_base
from app.api.schemas import ChatMessage
from app.evaluation.metrics import compute_ragas_scores

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="RAGAS 评估脚本")
    parser.add_argument("--dataset", type=str, required=True, help="评估数据集 JSON 路径")
    parser.add_argument("--knowledge-id", type=int, required=True, help="知识库 ID")
    parser.add_argument("--limit", type=int, default=None, help="限制跑 N 条（默认全量）")
    parser.add_argument("--output", type=str, default=None, help="结果保存路径")
    args = parser.parse_args()

    # 加载数据集
    with open(args.dataset, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    samples = dataset.get("samples", [])
    if args.limit:
        samples = samples[: args.limit]

    total = len(samples)
    print(f"\n{'=' * 60}")
    print(f"  RAGAS 评估")
    print(f"  数据集: {args.dataset}")
    print(f"  样本数: {total}")
    print(f"  知识库: {args.knowledge_id}")
    print(f"{'=' * 60}\n")

    questions = []
    answers = []
    contexts = []
    ground_truths = []
    per_sample_details = []

    start_time = time.time()

    for i, s in enumerate(samples):
        q_start = time.time()
        print(f"[{i + 1}/{total}] {s['question'][:50]}... ", end="", flush=True)

        try:
            ans, sources = chat_with_knowledge_base(
                knowledge_id=args.knowledge_id,
                query=s["question"],
                history=[ChatMessage(role="user", content=s["question"])],
            )
            questions.append(s["question"])
            answers.append(ans or "")
            contexts.append([src.chunk_content for src in sources])
            ground_truths.append(s.get("reference_answer", ""))

            elapsed = time.time() - q_start
            print(f"OK ({elapsed:.1f}s, {len(sources)} sources)")

            per_sample_details.append({
                "id": s["id"],
                "type": s.get("type", "unknown"),
                "question": s["question"],
                "answer": ans,
                "n_sources": len(sources),
                "expected_articles": s.get("source_articles", []),
            })
        except Exception as e:
            elapsed = time.time() - q_start
            print(f"FAIL ({elapsed:.1f}s, error: {e})")
            # 出错时填充空值以保持长度一致
            questions.append(s["question"])
            answers.append("")
            contexts.append([])
            ground_truths.append(s.get("reference_answer", ""))

    total_elapsed = time.time() - start_time
    print(f"\nQA 完成: {total} 条, 耗时 {total_elapsed:.1f}s ({total_elapsed / total:.1f}s/条)\n")

    # 计算 RAGAS 指标
    print("计算 RAGAS 指标...")
    ragas_start = time.time()
    scores = compute_ragas_scores(
        questions=questions,
        answers=answers,
        contexts=contexts,
        ground_truth=ground_truths,
    )
    ragas_elapsed = time.time() - ragas_start
    print(f"RAGAS 计算完成: {ragas_elapsed:.1f}s\n")

    # 打印结果
    print(f"{'=' * 60}")
    print(f"  RAGAS 评估结果")
    print(f"{'=' * 60}")
    ragas_metrics = {k: v for k, v in scores.items() if k != "per_sample"}
    for k, v in ragas_metrics.items():
        if v is None:
            print(f"  {k:25s}: 不支持")
        else:
            print(f"  {k:25s}: {v:.4f}")
    print(f"{'=' * 60}\n")

    # 每条详情
    print(f"{'明细':-^60}")
    per_sample_scores = scores.get("per_sample", {})
    for i, detail in enumerate(per_sample_details):
        print(f"\n  [{detail['id']}] ({detail['type']}) {detail['question'][:40]}...")
        for metric_name, vals in per_sample_scores.items():
            val = vals[i] if i < len(vals) else None
            if val is not None:
                print(f"    {metric_name}: {val:.4f}")
        print(f"    检索来源: {detail['n_sources']} 个 chunk")

    # 保存结果
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        output = {
            "dataset": args.dataset,
            "knowledge_id": args.knowledge_id,
            "n_samples": total,
            "qa_time_seconds": total_elapsed,
            "ragas_time_seconds": ragas_elapsed,
            "timestamp": time.time(),
            "metrics": {k: v for k, v in scores.items() if k != "per_sample"},
            "per_sample": [
                {**detail, "scores": {
                    m: vals[i] for m, vals in per_sample_scores.items()
                }}
                for i, detail in enumerate(per_sample_details)
            ],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存: {args.output}")


if __name__ == "__main__":
    main()
