"""
RAG 回归测试

每次 PR 自动运行，确保检索和生成质量不下降。

依赖：
  - ES 已运行且有 CI 种子数据（scripts/seed_eval_ci.py）
  - pytest
"""
import os
import sys
import pytest

# 确保能从项目根目录导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.evaluation.dataset import EvalDataset
from app.evaluation.runner import evaluate_retrieval

# PR 级只用 10 条核心用例
CORE_SAMPLES = 10

DATASET_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "dataset/eval_dataset_ip_customs_answerable_27.json",
)
KNOWLEDGE_ID = 1


@pytest.fixture(scope="module")
def core_dataset():
    ds = EvalDataset.from_json(DATASET_PATH)
    return ds.sample(CORE_SAMPLES, seed=42)


def test_retrieval_hit_rate(core_dataset):
    """检索 HitRate@5 应不低于 0.7"""
    result = evaluate_retrieval(KNOWLEDGE_ID, core_dataset, modes=["hybrid"])
    hr5 = result["summary"]["hybrid"]["hit_rate"][5]
    assert hr5 >= 0.7, f"HitRate@5 = {hr5}，期望 >= 0.7"


def test_retrieval_mrr(core_dataset):
    """检索 MRR@10 应不低于 0.5"""
    result = evaluate_retrieval(KNOWLEDGE_ID, core_dataset, modes=["hybrid"])
    mrr = result["summary"]["hybrid"]["mrr"]
    assert mrr >= 0.5, f"MRR@10 = {mrr}，期望 >= 0.5"


def test_retrieval_precision_at_1(core_dataset):
    """检索 Precision@1 应不低于 0.6"""
    result = evaluate_retrieval(KNOWLEDGE_ID, core_dataset, modes=["hybrid"])
    p1 = result["summary"]["hybrid"]["precision"][1]
    assert p1 >= 0.6, f"Precision@1 = {p1}，期望 >= 0.6"
