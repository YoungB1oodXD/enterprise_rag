# app/evaluation/runner.py
"""
统一评估入口

整合检索评估、端到端评估、全量评估，复现 app.retrieval.searcher.hybrid_search
（而非内联搜索实现），避免代码重复。
"""
import json
import os
import time
import logging
from typing import List, Dict, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.evaluation.dataset import EvalDataset
from app.evaluation.metrics import (
    compute_deterministic_scores,
    compute_ragas_scores,
    check_regression,
)

logger = get_logger(__name__)


def _ensure_es_imports():
    """延迟导入 ES 依赖，避免在纯数据集操作时触发"""
    from app.core.es_client import es as _es
    from app.retrieval.searcher import hybrid_search as _hybrid
    return _es, _hybrid


def evaluate_retrieval(
    knowledge_id: int,
    dataset: EvalDataset,
    modes: List[str] = None,
    k_list: List[int] = None,
    save_path: Optional[str] = None,
) -> Dict:
    """
    检索质量评估。

    对数据集中的每条问题执行检索，用 source_articles 作为 ground truth
    计算 HitRate / MRR / Precision / Recall。

    参数:
        knowledge_id: 知识库 ID
        dataset:      评估数据集
        modes:        检索模式（仅支持 "hybrid"，未来可扩展）
        k_list:       Top-K 列表
        save_path:    可选，JSON 结果保存路径

    返回:
        包含 summary（平均指标）和 per_sample（每条详情）的 dict
    """
    if modes is None:
        modes = ["hybrid"]
    if k_list is None:
        k_list = [1, 3, 5, 10]

    _es, hybrid_search = _ensure_es_imports()

    n = len(dataset.samples)
    logger.info(f"检索评估开始: {n} 条, modes={modes}")

    # 每条问题分别检索
    all_retrieved = {mode: [] for mode in modes}
    per_sample = []

    for i, sample in enumerate(dataset.samples):
        logger.info(f"[{i + 1}/{n}] 查询: {sample.question[:50]}...")

        for mode in modes:
            if mode == "hybrid":
                docs = hybrid_search(sample.question, knowledge_id)
            else:
                raise ValueError(f"不支持的检索模式: {mode}")

            all_retrieved[mode].append(docs)

        per_sample.append({
            "id": sample.id,
            "question": sample.question,
            "expected_articles": sample.source_articles,
            "n_retrieved": len(all_retrieved[mode][-1]),
        })

    # 计算指标
    summary = {}
    for mode in modes:
        summary[mode] = compute_deterministic_scores(
            all_retrieved[mode],
            [s.source_articles for s in dataset.samples],
            k_list=k_list,
        )

    result = {
        "type": "retrieval",
        "dataset": dataset.name,
        "n_samples": n,
        "knowledge_id": knowledge_id,
        "modes": modes,
        "k_list": k_list,
        "summary": summary,
        "per_sample": per_sample,
        "timestamp": time.time(),
    }

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"检索评估结果已保存: {save_path}")

    return result


def evaluate_end2end(
    knowledge_id: int,
    dataset: EvalDataset,
    use_ragas: bool = True,
    save_path: Optional[str] = None,
) -> Dict:
    """
    端到端 RAG 评估。

    对每条问题使用 qa_service.chat_with_knowledge_base 生成回答，
    然后计算确定性指标 + 可选 RAGAS 指标。

    参数:
        knowledge_id: 知识库 ID
        dataset:      评估数据集
        use_ragas:    是否计算 RAGAS 指标（需 LLM API Key）
        save_path:    可选，JSON 结果保存路径

    返回:
        包含各项指标的 dict
    """
    from app.services.qa_service import chat_with_knowledge_base
    from app.api.schemas import ChatMessage

    n = len(dataset.samples)
    logger.info(f"端到端评估开始: {n} 条")

    answers = []
    contexts = []
    per_sample = []

    for i, sample in enumerate(dataset.samples):
        logger.info(f"[{i + 1}/{n}] 查询: {sample.question[:50]}...")

        try:
            answer, sources = chat_with_knowledge_base(
                knowledge_id,
                sample.question,
                [ChatMessage(role="user", content=sample.question)],
            )
        except Exception as e:
            logger.error(f"QA 调用失败 (id={sample.id}): {e}")
            answer = ""
            sources = []

        answers.append(answer or "")
        context_texts = [s.get("chunk_content", "") for s in sources]
        contexts.append(context_texts)

        per_sample.append({
            "id": sample.id,
            "question": sample.question,
            "answer": answer,
            "n_sources": len(sources),
        })

    # 计算确定性指标
    result = {
        "type": "end2end",
        "dataset": dataset.name,
        "n_samples": n,
        "knowledge_id": knowledge_id,
        "per_sample": per_sample,
        "timestamp": time.time(),
    }

    # 如果 retrieval 字段已启用，先跑检索评估
    result["retrieval"] = evaluate_retrieval(knowledge_id, dataset, save_path=None)

    # RAGAS 指标
    if use_ragas:
        try:
            ragas_scores = compute_ragas_scores(
                [s.question for s in dataset.samples],
                answers,
                contexts,
                [s.reference_answer for s in dataset.samples],
            )
            result["ragas"] = ragas_scores
            logger.info(f"RAGAS 指标: {ragas_scores}")
        except Exception as e:
            logger.error(f"RAGAS 计算失败: {e}")
            result["ragas"] = {"error": str(e)}

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"端到端评估结果已保存: {save_path}")

    return result


def evaluate_full(
    knowledge_id: int,
    dataset_path: str,
    output_path: str,
    compare_baseline: Optional[str] = None,
    use_ragas: bool = True,
) -> Dict:
    """
    全量评估：检索 + 端到端 + RAGAS + 基线对比。

    参数:
        knowledge_id:    知识库 ID
        dataset_path:    数据集 JSON 路径
        output_path:     结果保存路径
        compare_baseline: 可选，基线结果 JSON 路径，用于回归检测
        use_ragas:       是否计算 RAGAS 指标

    返回:
        综合评估结果 dict
    """
    logger.info(f"全量评估开始: dataset={dataset_path}, knowledge_id={knowledge_id}")

    dataset = EvalDataset.from_json(dataset_path)
    logger.info(f"加载数据集: {dataset.name} ({len(dataset)} 条)")

    result = {
        "type": "full",
        "dataset": dataset.name,
        "dataset_path": dataset_path,
        "knowledge_id": knowledge_id,
        "n_samples": len(dataset),
        "timestamp": time.time(),
    }

    # 检索评估
    try:
        retrieval_result = evaluate_retrieval(knowledge_id, dataset, save_path=None)
        result["retrieval"] = retrieval_result["summary"]
    except Exception as e:
        logger.error(f"检索评估失败: {e}")
        result["retrieval"] = {"error": str(e)}

    # 端到端评估（含 RAGAS）
    try:
        e2e_result = evaluate_end2end(knowledge_id, dataset, use_ragas=use_ragas, save_path=None)
        for key in ("retrieval", "ragas", "per_sample"):
            if key in e2e_result:
                result[key] = e2e_result[key]
    except Exception as e:
        logger.error(f"端到端评估失败: {e}")
        result["ragas"] = {"error": str(e)}

    # 基线对比
    if compare_baseline and os.path.exists(compare_baseline):
        try:
            with open(compare_baseline, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            passed, regression_details = check_regression(result, baseline)
            result["regression"] = {
                "passed": passed,
                "details": regression_details,
                "baseline": compare_baseline,
            }
            logger.info(f"回归检测: {'通过' if passed else '失败'}")
        except Exception as e:
            logger.error(f"回归检测失败: {e}")

    # 保存结果
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"全量评估结果已保存: {output_path}")

    return result
