"""
统一全量评估脚本

对指定数据集执行完整的检索 + 端到端 + RAGAS 评估，
支持与基线结果对比进行回归检测。

用法：
  # 全量评估
  python scripts/run_full_eval.py \
      --dataset dataset/eval_dataset_ip_customs_balanced_30.json \
      --knowledge-id 1 \
      --output eval_results/result.json

  # 与基线对比
  python scripts/run_full_eval.py \
      --dataset dataset/eval_dataset_ip_customs_answerable_27.json \
      --knowledge-id 1 \
      --output eval_results/result.json \
      --compare eval_results/baseline.json

  # 跳过 RAGAS（仅确定性指标）
  python scripts/run_full_eval.py \
      --dataset dataset/eval_dataset_ip_customs_balanced_30.json \
      --knowledge-id 1 \
      --output eval_results/result.json \
      --no-ragas
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.logger import get_logger
from app.evaluation.runner import evaluate_full

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="RAG 全量评估")
    parser.add_argument(
        "--dataset", type=str, required=True,
        help="评估数据集 JSON 路径",
    )
    parser.add_argument(
        "--knowledge-id", type=int, required=True,
        help="知识库 ID",
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="评估结果保存路径",
    )
    parser.add_argument(
        "--compare", type=str, default=None,
        help="基线结果 JSON 路径（用于回归检测）",
    )
    parser.add_argument(
        "--no-ragas", action="store_true",
        help="跳过 RAGAS 指标计算（只跑确定性指标）",
    )
    args = parser.parse_args()

    # 验证数据集存在
    if not os.path.exists(args.dataset):
        logger.error(f"数据集文件不存在: {args.dataset}")
        sys.exit(1)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    logger.info(f"数据集: {args.dataset}")
    logger.info(f"知识库: {args.knowledge_id}")
    logger.info(f"输出:   {args.output}")
    logger.info(f"基线:   {args.compare or '无'}")
    logger.info(f"RAGAS:  {'跳过' if args.no_ragas else '启用'}")

    result = evaluate_full(
        knowledge_id=args.knowledge_id,
        dataset_path=args.dataset,
        output_path=args.output,
        compare_baseline=args.compare,
        use_ragas=not args.no_ragas,
    )

    # 打印摘要
    print("\n" + "=" * 60)
    print("  评估完成")
    print("=" * 60)

    retrieval = result.get("retrieval", {})
    if "error" not in retrieval:
        hybrid = retrieval.get("hybrid", {})
        print(f"  HitRate@5:  {hybrid.get('hit_rate', {}).get(5, 'N/A')}")
        print(f"  MRR@10:     {hybrid.get('mrr', 'N/A')}")

    ragas = result.get("ragas", {})
    if ragas and "error" not in ragas:
        print(f"  Faithfulness:      {ragas.get('faithfulness', 'N/A')}")
        print(f"  Answer Relevancy:  {ragas.get('answer_relevancy', 'N/A')}")
        print(f"  Context Precision: {ragas.get('context_precision', 'N/A')}")
        print(f"  Context Recall:    {ragas.get('context_recall', 'N/A')}")

    regression = result.get("regression", {})
    if regression:
        status = "通过" if regression.get("passed") else "失败"
        print(f"  回归检测: {status}")
        if regression.get("details", {}).get("regressed_metrics"):
            print(f"  退化指标: {regression['details']['regressed_metrics']}")

    print(f"  结果保存: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
