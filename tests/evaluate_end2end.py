"""
端到端 RAG 问答质量评估脚本

评估维度：
  1. ROUGE-L — 答案与参考答案的文本重合度（需 pip install rouge-score）
  2. Faithfulness — 答案是否忠于检索到的上下文（LLM-as-Judge）
  3. Rejection — 无答案题是否正确拒答

用法：
  # 跑全部 30 条（耗时较长，约 3-5 分钟）
  python tests/evaluate_end2end.py \
      --dataset dataset/eval_dataset_ip_customs_balanced_30.json \
      --knowledge_id 1 \
      --output tests/result_end2end.json

  # 先跑 5 条快速验证
  python tests/evaluate_end2end.py --limit 5

  # 跳过 LLM 评估（只测检索+拒答）
  python tests/evaluate_end2end.py --skip-retrieval-only

依赖（可选）：
  pip install rouge-score    # 用于 ROUGE-L
  pip install bert-score     # 用于 BERTScore（更准但更慢）

备注：
  需要配置 DASHSCOPE_API_KEY 环境变量，用于调用 LLM。
"""
import json
import os
import sys
import time
import argparse
import traceback
from typing import List, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.logger import get_logger
from app.services.qa_service import chat_with_knowledge_base, SYSTEM_PROMPT
from app.retrieval.searcher import hybrid_search

logger = get_logger(__name__)


# ================================================================
# LLM-as-Judge：判断答案是否忠于检索上下文
# ================================================================

_JUDGE_CLIENT = None


def _get_judge_client():
    global _JUDGE_CLIENT
    if _JUDGE_CLIENT is not None:
        return _JUDGE_CLIENT
    if not settings.rag.llm_api_key:
        raise ValueError("DASHSCOPE_API_KEY 未配置")
    from openai import OpenAI
    _JUDGE_CLIENT = OpenAI(
        api_key=settings.rag.llm_api_key,
        base_url=settings.rag.llm_base_url,
    )
    return _JUDGE_CLIENT


def faithfulness_check(question: str, answer: str, context_snippet: str) -> bool:
    """
    用 LLM 判断答案是否忠于提供的上下文。
    返回 True = 忠实（faithful），False = 不忠实（hallucination）。
    """
    if not answer or not context_snippet:
        return False
    try:
        client = _get_judge_client()
        prompt = f"""你是一个严格的 faithfulness 评估者。判断以下答案是否完全基于提供的上下文，没有编造内容。

[上下文]:
{context_snippet[:2000]}

[问题]:
{question}

[答案]:
{answer}

请只输出 "faithful"（完全基于上下文）或 "unfaithful"（包含上下文之外的编造内容）。"""
        resp = client.chat.completions.create(
            model=settings.rag.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        result = resp.choices[0].message.content.strip().lower()
        return "faithful" in result and "unfaithful" not in result
    except Exception as e:
        logger.warning(f"Faithfulness 判断失败: {e}")
        return False


# ================================================================
# ROUGE-L（可选）
# ================================================================

_ROUGE_AVAILABLE = False
try:
    from rouge_score import rouge_scorer
    _ROUGE_AVAILABLE = True
except ImportError:
    logger.warning("rouge-score 未安装，ROUGE-L 将跳过。pip install rouge-score")


def compute_rouge_l(reference: str, hypothesis: str) -> Optional[float]:
    if not _ROUGE_AVAILABLE or not reference or not hypothesis:
        return None
    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)
    scores = scorer.score(reference, hypothesis)
    return scores["rougeL"].fmeasure


# ================================================================
# BERTScore（可选）
# ================================================================

_BERTSCORE_AVAILABLE = False
try:
    from bert_score import score as bert_score_fn
    _BERTSCORE_AVAILABLE = True
except ImportError:
    logger.warning("bert-score 未安装，BERTScore 将跳过。pip install bert-score")


def compute_bert_score(reference: str, hypothesis: str) -> Optional[float]:
    if not _BERTSCORE_AVAILABLE or not reference or not hypothesis:
        return None
    try:
        _, _, f1 = bert_score_fn([hypothesis], [reference], lang="zh", verbose=False)
        return float(f1[0])
    except Exception as e:
        logger.warning(f"BERTScore 计算失败: {e}")
        return None


# ================================================================
# 拒答检测
# ================================================================

_REJECT_PATTERNS = [
    "未找到相关内容",
    "无法准确回答",
    "没有检索到",
    "知识库中未找到",
    "无法回答",
    "不在知识库",
    "未涉及",
    "抱歉",
    "sorry",
]


def is_rejection(answer: str) -> bool:
    """检测答案是否为拒答"""
    if not answer:
        return False
    lower = answer.lower()
    for pattern in _REJECT_PATTERNS:
        if pattern.lower() in lower:
            return True
    return False


# ================================================================
# 上下文摘要（给 faithfulness 判断用）
# ================================================================

def summarize_context(retrieved_docs: List[Dict], max_chars: int = 2000) -> str:
    """拼接检索到的文档块摘要"""
    parts = []
    total = 0
    for doc in retrieved_docs[:5]:
        content = doc.get("chunk_content", "")[:500]
        breadcrumb = doc.get("breadcrumb", "")
        chunk = f"[{breadcrumb}] {content}"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts)


# ================================================================
# 主流程
# ================================================================

def evaluate_end2end(
    dataset_path: str,
    knowledge_id: int,
    output_path: str,
    limit: Optional[int] = None,
    skip_llm: bool = False,
):
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    samples = dataset["samples"]
    if limit:
        samples = samples[:limit]
    n = len(samples)
    logger.info(f"加载评估集: {dataset_path} → {n} 条（共 {len(dataset['samples'])} 条）")

    # 统计
    results = []
    total_time = 0.0
    rejection_correct = 0
    rejection_total = 0
    answerable_total = 0

    rouge_l_scores = []
    bert_score_scores = []
    faithful_count = 0
    faithful_total = 0

    for i, sample in enumerate(samples):
        qid = sample.get("id", i + 1)
        question = sample["question"]
        expected = sample.get("reference_answer")
        qtype = sample.get("type", "")
        is_no_answer = qtype == "no_answer"

        logger.info(f"[{i + 1}/{n}] ID={qid} [{qtype}] {'[拒答]' if is_no_answer else '[可答]'}: {question[:50]}...")

        start = time.time()
        try:
            # 模拟单轮对话
            from app.api.schemas import ChatMessage
            history = [ChatMessage(role="user", content=question)]
            answer, sources = chat_with_knowledge_base(knowledge_id, question, history)
        except Exception as e:
            logger.error(f"ID={qid} 处理失败: {traceback.format_exc()}")
            answer = f"[ERROR] {str(e)}"
            sources = []
        elapsed = time.time() - start
        total_time += elapsed

        # 判断拒答
        rejected = is_rejection(answer)

        per_sample = {
            "id": qid,
            "type": qtype,
            "question": question,
            "expected_answer": expected,
            "actual_answer": answer,
            "n_sources": len(sources),
            "is_rejection": rejected,
            "elapsed_seconds": round(elapsed, 2),
        }

        # ── 无答案题 ──────────────────────────────────────────
        if is_no_answer:
            rejection_total += 1
            if rejected:
                rejection_correct += 1
                per_sample["rejection_correct"] = True
            else:
                per_sample["rejection_correct"] = False
                logger.warning(f"  ⚠ 拒答题未拒答: {answer[:80]}...")

        # ── 可答题 ────────────────────────────────────────────
        else:
            answerable_total += 1
            per_sample["rejection_correct"] = None

            # ROUGE-L
            if expected and _ROUGE_AVAILABLE:
                rouge_l = compute_rouge_l(expected, answer)
                per_sample["rouge_l"] = rouge_l
                if rouge_l is not None:
                    rouge_l_scores.append(rouge_l)
            else:
                per_sample["rouge_l"] = None

            # BERTScore
            if expected and _BERTSCORE_AVAILABLE:
                bs = compute_bert_score(expected, answer)
                per_sample["bert_score"] = bs
                if bs is not None:
                    bert_score_scores.append(bs)
            else:
                per_sample["bert_score"] = None

            # Faithfulness（不跳过 LLM 且检索到内容时）
            if not skip_llm and sources:
                context_str = summarize_context(
                    hybrid_search(question, knowledge_id)
                )
                faithful = faithfulness_check(question, answer, context_str)
                per_sample["faithful"] = faithful
                if faithful:
                    faithful_count += 1
                faithful_total += 1
            else:
                per_sample["faithful"] = None

        results.append(per_sample)

        # 进度摘要
        logger.info(f"  → {elapsed:.1f}s | 拒答={rejected} | 来源={len(sources)} | {answer[:60]}...")

    # ── 汇总 ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(f"  端到端 RAG 评估结果")
    print(f"  数据集: {os.path.basename(dataset_path)} | 评估 {n} 条 | 总耗时 {total_time:.1f}s")
    print("=" * 80)

    # 拒答统计
    if rejection_total > 0:
        rejection_rate = rejection_correct / rejection_total
        print(f"\n  拒答能力:")
        print(f"    无答案题: {rejection_total} 条")
        print(f"    正确拒答: {rejection_correct} 条")
        print(f"    拒答准确率: {rejection_rate:.2%}")
    else:
        rejection_rate = None
        print(f"\n  拒答能力: 本数据集中无拒答题")

    # 可答题统计
    if answerable_total > 0:
        print(f"\n  可答题: {answerable_total} 条")

        # ROUGE-L
        if rouge_l_scores:
            avg_rouge = sum(rouge_l_scores) / len(rouge_l_scores)
            print(f"  ROUGE-L (avg):    {avg_rouge:.4f}")
        else:
            avg_rouge = None
            print(f"  ROUGE-L:          未计算（pip install rouge-score）")

        # BERTScore
        if bert_score_scores:
            avg_bert = sum(bert_score_scores) / len(bert_score_scores)
            print(f"  BERTScore (avg):  {avg_bert:.4f}")
        else:
            avg_bert = None
            print(f"  BERTScore:        未计算（pip install bert-score）")

        # Faithfulness
        if faithful_total > 0:
            faithful_rate = faithful_count / faithful_total
            print(f"  Faithfulness:     {faithful_count}/{faithful_total} = {faithful_rate:.2%}")
        else:
            faithful_rate = None
            print(f"  Faithfulness:     未评估")

        # 平均耗时
        avg_time = total_time / n
        print(f"  平均每条耗时:     {avg_time:.1f}s")
    else:
        avg_rouge = avg_bert = faithful_rate = None

    print("\n" + "=" * 80)

    # ── 保存 ──────────────────────────────────────────────
    summary = {
        "dataset": dataset_path,
        "n_samples": n,
        "knowledge_id": knowledge_id,
        "total_time_seconds": round(total_time, 1),
        "avg_time_per_sample": round(total_time / n, 1) if n > 0 else 0,
        "rejection": {
            "total": rejection_total,
            "correct": rejection_correct,
            "accuracy": round(rejection_rate, 4) if rejection_rate else None,
        },
        "answerable": {
            "total": answerable_total,
            "rouge_l_avg": round(avg_rouge, 4) if avg_rouge else None,
            "bert_score_avg": round(avg_bert, 4) if avg_bert else None,
            "faithfulness_rate": round(faithful_rate, 4) if faithful_rate else None,
        },
        "per_sample": results,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存: {output_path}")

    return summary


# ================================================================
# CLI 入口
# ================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="端到端 RAG 问答质量评估")
    parser.add_argument("--dataset", default="dataset/eval_dataset_ip_customs_balanced_30.json",
                        help="评估集 JSON 路径")
    parser.add_argument("--knowledge_id", type=int, default=1)
    parser.add_argument("--output", default="tests/result_end2end.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制评估条数（快速调试用）")
    parser.add_argument("--skip-llm", action="store_true",
                        help="跳过 LLM 相关评估（只测检索+拒答）")
    args = parser.parse_args()

    evaluate_end2end(
        dataset_path=args.dataset,
        knowledge_id=args.knowledge_id,
        output_path=args.output,
        limit=args.limit,
        skip_llm=args.skip_llm,
    )
