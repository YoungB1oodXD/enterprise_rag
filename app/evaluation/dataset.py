# app/evaluation/dataset.py
"""
统一评估数据集管理

从现有 JSON 数据集加载，支持转换为 RAGAS HuggingFace Dataset 格式、
按类型过滤、随机采样、以及生成 CI 环境 ES 数据种子。
"""
import json
import random
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class EvalSample:
    id: int
    type: str
    question: str
    reference_answer: str
    source_articles: List[str] = field(default_factory=list)
    reference_contexts: List[str] = field(default_factory=list)


@dataclass
class EvalDataset:
    """统一评估数据集"""

    name: str
    samples: List[EvalSample]

    @classmethod
    def from_json(cls, path: str) -> "EvalDataset":
        """从现有 JSON 数据集文件加载"""
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        samples = [
            EvalSample(
                id=s.get("id", i + 1),
                type=s.get("type", "unknown"),
                question=s["question"],
                reference_answer=s.get("reference_answer", ""),
                source_articles=s.get("source_articles", []),
                reference_contexts=s.get("reference_contexts", []),
            )
            for i, s in enumerate(raw.get("samples", raw if isinstance(raw, list) else []))
        ]
        name = raw.get("eval_dataset_name", path)
        return cls(name=name, samples=samples)

    def to_ragas_format(self, answers: List[str], contexts: List[List[str]]) -> "dict":
        """
        转换为 RAGAS HuggingFace Dataset 所需的列数据。

        参数:
            answers:   每个问题对应的 RAG 回答列表
            contexts:  每个问题对应的检索上下文列表（每个元素是 chunk 列表）

        返回:
            dict，可直接用于 datasets.Dataset.from_dict()
        """
        assert len(self.samples) == len(answers) == len(contexts), \
            f"samples({len(self.samples)}) answers({len(answers)}) contexts({len(contexts)}) 长度不一致"

        return {
            "question": [s.question for s in self.samples],
            "answer": answers,
            "contexts": contexts,
            "ground_truth": [s.reference_answer for s in self.samples],
        }

    def to_ci_seed(self, knowledge_id: int = 1, document_id: int = 1) -> List[dict]:
        """
        生成 CI 环境 ES 文档和 chunk 数据种子。

        从数据集构造精简的 ES 文档和 chunk，
        使 CI 环境无需真实上传文件即可运行检索评估。
        """
        chunks = []
        for s in self.samples:
            for art in s.source_articles:
                chunks.append({
                    "knowledge_id": knowledge_id,
                    "document_id": document_id,
                    "chunk_content": f"第{art}条 知识产权海关保护",
                    "breadcrumb": f"知识产权海关保护条例 > 第{art}条",
                    "embedding_vector": None,
                })
        return chunks

    def filter_by_type(self, types: List[str]) -> "EvalDataset":
        """按问题类型过滤"""
        filtered = [s for s in self.samples if s.type in types]
        result = EvalDataset(name=f"{self.name} (filtered: {types})", samples=filtered)
        return result

    def sample(self, n: int, seed: int = 42) -> "EvalDataset":
        """随机采样 n 条"""
        rng = random.Random(seed)
        sampled = rng.sample(self.samples, min(n, len(self.samples)))
        return EvalDataset(name=f"{self.name} (sampled: {n})", samples=sampled)

    def __len__(self) -> int:
        return len(self.samples)
