"""评价指标单元测试（mock LLM，无需 ES）

测试覆盖：
  1. EvalDataset 加载、过滤、采样
  2. compute_deterministic_scores 核心逻辑
  3. check_regression 回归检测
"""

import json
import tempfile
import os
import pytest
from app.evaluation.dataset import EvalDataset
from app.evaluation.metrics import (
    compute_deterministic_scores,
    check_regression,
)


# ================================================================
# 测试数据
# ================================================================

SAMPLE_DATASET = {
    "eval_dataset_name": "测试集",
    "samples": [
        {
            "id": 1,
            "type": "exact_clause",
            "question": "测试问题1？",
            "reference_answer": "这是参考答案1。",
            "source_articles": ["第十条"],
        },
        {
            "id": 2,
            "type": "semantic_rewrite",
            "question": "测试问题2？",
            "reference_answer": "这是参考答案2。",
            "source_articles": ["第八条", "第九条"],
        },
    ],
}


# ================================================================
# EvalDataset 测试
# ================================================================


class TestEvalDataset:

    def test_from_json(self):
        """从 JSON 文件加载数据集"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(SAMPLE_DATASET, f, ensure_ascii=False)
            tmp_path = f.name
        try:
            ds = EvalDataset.from_json(tmp_path)
            assert len(ds) == 2
            assert ds.name == "测试集"
            assert ds.samples[0].question == "测试问题1？"
            assert ds.samples[0].source_articles == ["第十条"]
            assert ds.samples[1].source_articles == ["第八条", "第九条"]
        finally:
            os.unlink(tmp_path)

    def test_filter_by_type(self):
        """按类型过滤"""
        ds = EvalDataset(name="t", samples=[
            type("s", (), {"type": "a", "question": "q1", "reference_answer": "", "source_articles": [], "reference_contexts": [], "id": 1})(),
            type("s", (), {"type": "b", "question": "q2", "reference_answer": "", "source_articles": [], "reference_contexts": [], "id": 2})(),
        ])
        filtered = ds.filter_by_type(["a"])
        assert len(filtered) == 1
        assert filtered.samples[0].id == 1

    def test_sample(self):
        """随机采样"""
        ds = EvalDataset(name="t", samples=[
            type("s", (), {"type": "a", "question": f"q{i}", "reference_answer": "", "source_articles": [], "reference_contexts": [], "id": i})()
            for i in range(10)
        ])
        sampled = ds.sample(3)
        assert len(sampled) == 3

    def test_sample_exceeds_length(self):
        """采样数超过总数时返回全部"""
        ds = EvalDataset(name="t", samples=[
            type("s", (), {"type": "a", "question": "q1", "reference_answer": "", "source_articles": [], "reference_contexts": [], "id": 1})(),
        ])
        sampled = ds.sample(10)
        assert len(sampled) == 1

    def test_to_ragas_format(self):
        """RAGAS 格式转换"""
        ds = EvalDataset(name="t", samples=[
            type("s", (), {"type": "a", "question": "q1", "reference_answer": "a1", "source_articles": [], "reference_contexts": [], "id": 1})(),
            type("s", (), {"type": "a", "question": "q2", "reference_answer": "a2", "source_articles": [], "reference_contexts": [], "id": 2})(),
        ])
        ragas = ds.to_ragas_format(["ans1", "ans2"], [["ctx1"], ["ctx2"]])
        assert ragas["question"] == ["q1", "q2"]
        assert ragas["answer"] == ["ans1", "ans2"]
        assert ragas["contexts"] == [["ctx1"], ["ctx2"]]
        assert ragas["ground_truth"] == ["a1", "a2"]

    def test_to_ragas_format_length_mismatch(self):
        """长度不匹配应断言"""
        ds = EvalDataset(name="t", samples=[
            type("s", (), {"type": "a", "question": "q1", "reference_answer": "a1", "source_articles": [], "reference_contexts": [], "id": 1})(),
        ])
        with pytest.raises(AssertionError):
            ds.to_ragas_format(["ans1", "ans2"], [["ctx1"]])

    def test_to_ci_seed(self):
        """CI 种子数据生成"""
        ds = EvalDataset(name="t", samples=[
            type("s", (), {"type": "a", "question": "q", "reference_answer": "a", "source_articles": ["第十条", "第十一条"], "reference_contexts": [], "id": 1})(),
        ])
        seeds = ds.to_ci_seed(knowledge_id=5, document_id=3)
        assert len(seeds) == 2
        assert seeds[0]["knowledge_id"] == 5
        assert seeds[0]["document_id"] == 3
        assert "第十条" in seeds[0]["chunk_content"]


# ================================================================
# 确定性指标测试
# ================================================================


class TestDeterministicScores:

    def test_perfect_match(self):
        """完美命中：第一条就匹配"""
        chunks = [[
            {"breadcrumb": "条例 > 第十条"},
            {"breadcrumb": "条例 > 第二十条"},
        ]]
        expected = [["第十条"]]
        scores = compute_deterministic_scores(chunks, expected, k_list=[1, 5])
        assert scores["hit_rate"][1] == 1.0
        assert scores["mrr"] == 1.0
        assert scores["precision"][5] == 0.2  # 1 relevant / 5
        assert scores["recall"][5] == 1.0  # 1/1

    def test_no_match(self):
        """无匹配"""
        chunks = [[
            {"breadcrumb": "条例 > 第二十条"},
            {"breadcrumb": "条例 > 第三十条"},
        ]]
        expected = [["第十条"]]
        scores = compute_deterministic_scores(chunks, expected, k_list=[1, 5])
        assert scores["hit_rate"][1] == 0.0
        assert scores["mrr"] == 0.0

    def test_second_rank_match(self):
        """第二条匹配"""
        chunks = [[
            {"breadcrumb": "条例 > 第二十条"},
            {"breadcrumb": "条例 > 第十条"},
        ]]
        expected = [["第十条"]]
        scores = compute_deterministic_scores(chunks, expected, k_list=[1, 5])
        assert scores["hit_rate"][1] == 0.0  # top-1 没命中
        assert scores["hit_rate"][5] == 1.0  # top-5 命中
        assert scores["mrr"] == 0.5  # 1/2

    def test_multiple_expected_articles(self):
        """多个期望条号"""
        chunks = [[
            {"breadcrumb": "条例 > 第八条"},
            {"breadcrumb": "条例 > 第十条"},
            {"breadcrumb": "条例 > 第二十条"},
        ]]
        expected = [["第八条", "第九条"]]
        scores = compute_deterministic_scores(chunks, expected, k_list=[1])
        assert scores["hit_rate"][1] == 1.0
        assert scores["precision"][1] == 1.0

    def test_empty_input(self):
        """空输入应返回零值"""
        scores = compute_deterministic_scores([], [], k_list=[1])
        assert scores["hit_rate"][1] == 0.0
        assert scores["mrr"] == 0.0

    def test_article_number_extraction_complex(self):
        """复杂条号格式（中文数字）"""
        chunks = [[
            {"breadcrumb": "第二章 > 第十条 > 第三款"},
        ]]
        expected = [["第十条"]]
        scores = compute_deterministic_scores(chunks, expected, k_list=[1])
        assert scores["hit_rate"][1] == 1.0


# ================================================================
# 回归检测测试
# ================================================================


class TestRegressionCheck:

    def test_no_regression(self):
        """无回归"""
        baseline = {"hit_rate": {5: 0.85}, "mrr": 0.72}
        current = {"hit_rate": {5: 0.88}, "mrr": 0.75}
        passed, details = check_regression(current, baseline)
        assert passed is True
        assert details["regressed_metrics"] == []

    def test_with_regression(self):
        """有回归"""
        baseline = {"hit_rate": {5: 0.85}, "mrr": 0.72}
        current = {"hit_rate": {5: 0.60}, "mrr": 0.50}
        passed, details = check_regression(current, baseline)
        assert passed is False
        assert len(details["regressed_metrics"]) > 0

    def test_custom_threshold(self):
        """自定义阈值"""
        baseline = {"hit_rate@5": 0.85}
        current = {"hit_rate@5": 0.80}
        passed, details = check_regression(current, baseline, thresholds={"hit_rate@5": 0.1})
        assert passed is True  # delta -0.05 < threshold 0.1

    def test_missing_keys(self):
        """部分指标缺失不应崩溃"""
        baseline = {"hit_rate": {5: 0.85}}
        current = {"mrr": 0.72}
        passed, details = check_regression(current, baseline)
        assert passed is True  # 没有重叠指标

    def test_flat_nested_dict(self):
        """嵌套 dict 展平"""
        baseline = {"hit_rate": {5: 0.85, 10: 0.90}}
        current = {"hit_rate": {5: 0.70, 10: 0.88}}
        passed, details = check_regression(current, baseline)
        assert passed is False
        assert "hit_rate@5" in details["regressed_metrics"]
