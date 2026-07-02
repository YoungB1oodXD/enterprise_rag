# app/evaluation/metrics.py
"""
RAG 评估指标

提供两类指标：
  1. RAGAS 指标（需 LLM）：faithfulness, answer_relevancy, context_precision, context_recall
  2. 确定性指标（无需 LLM）：HitRate, MRR, Precision, Recall

以及回归检测功能。
"""
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ================================================================
# 确定性指标（不依赖 LLM，可在 CI 中稳定运行）
# ================================================================


def compute_deterministic_scores(
    retrieved_chunks: List[List[dict]],
    expected_articles: List[List[str]],
    k_list: List[int] = None,
) -> Dict:
    """
    计算确定性检索指标（HitRate/MRR/Precision/Recall）。

    参数:
        retrieved_chunks:  每个问题检索到的 chunk 列表（已归一化的 dict，含 breadcrumb）
        expected_articles: 每个问题期望命中的条号列表，如 ["第十条", "第十一条"]
        k_list:            要计算的 K 值列表

    返回:
        {
            "hit_rate": {1: ..., 3: ..., 5: ..., 10: ...},
            "mrr": ...,
            "precision": {1: ..., 3: ..., ...},
            "recall": {1: ..., 3: ..., ...},
        }
    """
    import re

    if k_list is None:
        k_list = [1, 3, 5, 10]

    def _extract_article_numbers(breadcrumb: str) -> List[str]:
        """从面包屑提取条号"""
        parts = breadcrumb.split(" > ")
        result = []
        for part in parts:
            m = re.search(r"第[一二三四五六七八九十\d]+条", part)
            if m:
                result.append(m.group())
        return result

    def _is_chunk_relevant(chunk: dict, expected: List[str]) -> bool:
        """通过条号匹配判断 chunk 是否相关"""
        chunk_articles = _extract_article_numbers(chunk.get("breadcrumb", ""))
        return any(art in chunk_articles for art in expected)

    n = len(retrieved_chunks)
    if n == 0:
        return {
            "hit_rate": {k: 0.0 for k in k_list},
            "mrr": 0.0,
            "precision": {k: 0.0 for k in k_list},
            "recall": {k: 0.0 for k in k_list},
        }

    # 累计指标
    total_hit_rate = {k: 0.0 for k in k_list}
    total_precision = {k: 0.0 for k in k_list}
    total_recall = {k: 0.0 for k in k_list}
    total_mrr = 0.0

    for i in range(n):
        relevance = [_is_chunk_relevant(d, expected_articles[i]) for d in retrieved_chunks[i]]
        found_positions = [idx + 1 for idx, r in enumerate(relevance) if r]

        total_relevant = sum(relevance)
        first_rank = found_positions[0] if found_positions else None

        for k in k_list:
            top_k_rel = relevance[:k]
            hits = sum(top_k_rel)
            total_hit_rate[k] += 1.0 if hits > 0 else 0.0
            total_precision[k] += hits / k if k > 0 else 0.0
            total_recall[k] += hits / total_relevant if total_relevant > 0 else 0.0

        total_mrr += (1.0 / first_rank) if first_rank and first_rank <= 10 else 0.0

    # 求平均
    return {
        "hit_rate": {k: round(total_hit_rate[k] / n, 4) for k in k_list},
        "mrr": round(total_mrr / n, 4),
        "precision": {k: round(total_precision[k] / n, 4) for k in k_list},
        "recall": {k: round(total_recall[k] / n, 4) for k in k_list},
    }


# ================================================================
# RAGAS 指标（依赖 LLM Judge）
# ================================================================


def _compute_ragas_without_llm(
    questions: List[str],
    answers: List[str],
    contexts: List[List[str]],
    ground_truth: List[str],
) -> Dict:
    """
    无 LLM 可用时，降级到基于文本的 ROUGE-L + BERTScore 近似指标。
    """
    metrics = {}
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        rouge_scores = [scorer.score(gt, ans)["rougeL"].fmeasure for gt, ans in zip(ground_truth, answers)]
        metrics["rougeL"] = round(sum(rouge_scores) / len(rouge_scores), 4) if rouge_scores else 0.0
    except ImportError:
        logger.warning("rouge-score 未安装，跳过 ROUGE-L 计算")
        metrics["rougeL"] = None

    try:
        from bert_score import score as bert_score
        _, _, f1 = bert_score(answers, ground_truth, lang="zh", verbose=False)
        metrics["bertscore_f1"] = round(f1.mean().item(), 4)
    except ImportError:
        logger.warning("bert-score 未安装，跳过 BERTScore 计算")
        metrics["bertscore_f1"] = None

    return metrics


def _setup_ragas_llm(use_cache: bool = True):
    """
    为 RAGAS 配置 LLM（基于项目现有的 DashScope 配置）。
    返回 (llm, embeddings) 元组。

    注意：RAGAS Judge 的 prompt 较长（含 context），
    必须设置足够大的 max_tokens 避免输出被截断。

    参数:
        use_cache: 启用磁盘缓存，重跑时 LLM 调用直接返回缓存结果（快 60x）
    """
    import os
    from app.core.config import settings

    # RAGAS embedding_factory 从环境变量读 API Key
    os.environ["OPENAI_API_KEY"] = settings.rag.llm_api_key

    from openai import OpenAI
    from ragas.llms import llm_factory

    client = OpenAI(
        base_url=settings.rag.llm_base_url,
        api_key=settings.rag.llm_api_key,
    )
    extra_kwargs = dict(max_tokens=16384)  # 覆盖 InstructorModelArgs 默认 1024

    if use_cache:
        from ragas.cache import DiskCacheBackend
        cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "eval_results", ".ragas_cache"
        )
        os.makedirs(cache_dir, exist_ok=True)
        extra_kwargs["cache"] = DiskCacheBackend(cache_dir)

    llm = llm_factory(model=settings.rag.llm_model, client=client, **extra_kwargs)
    return llm


def compute_ragas_scores(
    questions: List[str],
    answers: List[str],
    contexts: List[List[str]],
    ground_truth: Optional[List[str]] = None,
    max_contexts: int = 3,
    max_chars_per_context: int = 500,
) -> Dict:
    """
    使用 RAGAS 计算标准化指标。

    使用项目配置的 LLM（DashScope OpenAI-compatible API）作为 Judge。
    当 RAGAS 不可用时自动降级到 ROUGE-L + BERTScore。

    注意:
      - RAGAS 0.4.x 通过 llm_factory + InstructorLLM 驱动
      - Faithfulness / ContextPrecision / ContextRecall 仅需 LLM
      - AnswerRelevancy / AnswerCorrectness 需要 embedding API，
        DashScope 兼容度有限暂不支持，会自动跳过

    返回:
        {
            "faithfulness": ...,
            "context_precision": ...,
            "context_recall": ...,
            "answer_relevancy": ...,         # 可能为 None
            "answer_correctness": ...,       # 可能为 None
            "per_sample": {...},             # 每条详情
            "rougeL": ...,                   # 降级指标
            "bertscore_f1": ...,             # 降级指标
        }
    """
    assert len(questions) == len(answers) == len(contexts), \
        f"输入长度不一致: Q={len(questions)} A={len(answers)} C={len(contexts)}"

    if not questions:
        return {}

    # 截断 context 避免 RAGAS Judge 输出被 max_tokens 截断
    # 只保留 top N 个 chunks，每个 chunk 截断到 max_chars_per_context 字符
    contexts = [
        [chunk[:max_chars_per_context] for chunk in ctx[:max_contexts]]
        for ctx in contexts
    ]

    result = {}

    # 尝试 RAGAS
    ragas_available = False
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            context_precision,
            context_recall,
        )

        # 配置 LLM
        llm = _setup_ragas_llm()
        faithfulness.llm = llm
        context_precision.llm = llm
        context_recall.llm = llm

        data = {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
        }
        if ground_truth:
            from ragas.metrics import answer_correctness
            data["ground_truth"] = ground_truth
        else:
            answer_correctness = None

        dataset = Dataset.from_dict(data)

        metrics_list = [faithfulness, context_precision, context_recall]

        scores = evaluate(dataset, metrics=metrics_list)

        # RAGAS 0.4.x EvaluationResult 按 metric.name 访问
        for m in metrics_list:
            try:
                vals = scores[m.name]
                result[m.name] = round(sum(vals) / len(vals), 4) if vals else 0.0
            except Exception as e:
                logger.warning(f"RAGAS {m.name} 获取结果失败: {e}")
                result[m.name] = None

        # per_sample 详情
        result["per_sample"] = {}
        for m in metrics_list:
            try:
                vals = scores[m.name]
                result["per_sample"][m.name] = [round(float(v), 4) for v in vals]
            except Exception:
                pass

        ragas_available = True
    except ImportError as e:
        logger.warning(f"RAGAS 导入失败 ({e})，降级到确定性指标")
    except Exception as e:
        logger.warning(f"RAGAS 计算失败 ({e})，降级到确定性指标")

    if not ragas_available and ground_truth:
        fallback = _compute_ragas_without_llm(questions, answers, contexts, ground_truth)
        result.update(fallback)

    return result


# ================================================================
# 回归检测
# ================================================================


def check_regression(
    current: Dict,
    baseline: Dict,
    thresholds: Dict[str, float] = None,
) -> Tuple[bool, Dict]:
    """
    回归检测：对比当前指标与基线，判断是否有显著下降。

    参数:
        current:   当前评估结果（{metric_name: value} 平面结构）
        baseline:  基线评估结果
        thresholds: 各指标允许的最大下降幅度（默认 0.05）

    返回:
        (pass: bool, details: dict)
        details 格式: {metric_name: {"current": ..., "baseline": ..., "delta": ..., "regressed": bool}}
    """
    if thresholds is None:
        thresholds = {}

    # 展平嵌套指标（如 hit_rate -> hit_rate@5, hit_rate@10）
    def _flatten(d: dict, prefix: str = "") -> dict:
        flat = {}
        for k, v in d.items():
            key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                flat.update(_flatten(v, prefix=f"{key}@"))
            elif isinstance(v, (int, float)):
                flat[key] = v
        return flat

    current_flat = _flatten(current)
    baseline_flat = _flatten(baseline)

    all_keys = set(current_flat.keys()) | set(baseline_flat.keys())
    default_threshold = 0.05

    regressed = []
    passed = True

    for key in sorted(all_keys):
        cur_val = current_flat.get(key)
        base_val = baseline_flat.get(key)
        if cur_val is None or base_val is None:
            continue

        delta = round(cur_val - base_val, 4)
        threshold = thresholds.get(key, default_threshold)

        is_regressed = delta < -threshold
        if is_regressed:
            passed = False
            regressed.append(key)

    details = {
        "passed": passed,
        "regressed_metrics": regressed,
        "thresholds": {k: thresholds.get(k, default_threshold) for k in all_keys},
    }

    return passed, details
