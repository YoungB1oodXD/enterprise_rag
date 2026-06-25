"""
构建评估数据集：从 ES 读取文档 chunks，用 LLM 生成 Q&A 对，输出 JSON 文件。

用法：
  python scripts/build_eval_dataset.py --knowledge_id 1 --num_questions 30 --output scripts/eval_dataset.json
"""
import json
import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.es_client import es
from app.core.logger import get_logger
from app.core.llm_client import get_llm_client

logger = get_logger(__name__)


def fetch_all_chunks(knowledge_id: int) -> list:
    """从 ES 读取指定知识库的所有文档 chunks。"""
    index = settings.es.index_chunk_info
    if not es.indices.exists(index=index):
        logger.error(f"ES 索引 {index} 不存在")
        return []

    query = {"query": {"term": {"knowledge_id": knowledge_id}}, "size": 1000}
    res = es.search(index=index, body=query)
    hits = res["hits"]["hits"]
    chunks = []
    seen = set()
    for hit in hits:
        src = hit["_source"]
        content = src.get("chunk_content", "")
        if not content or content in seen:
            continue
        seen.add(content)
        chunks.append({
            "chunk_content": content,
            "breadcrumb": src.get("breadcrumb", ""),
            "document_id": src.get("document_id", 0),
            "page_number": src.get("page_number", 1),
        })
    logger.info(f"知识库 {knowledge_id} 共读取 {len(chunks)} 个 chunks（去重后）")
    return chunks


def generate_qa_pairs(chunks: list, num_questions: int) -> list:
    """用 LLM 为 chunks 生成 Q&A 对。"""
    if not chunks:
        return []

    client = get_llm_client()
    samples = []

    for i, chunk in enumerate(chunks):
        if len(samples) >= num_questions:
            break

        prompt = f"""根据以下资料生成一个中文问答对。问题要有实际价值，答案必须严格基于资料内容。

资料内容：
{chunk['chunk_content']}

以 JSON 格式输出，不要任何其他文字：
{{"question": "你的问题", "answer": "你的答案"}}"""

        try:
            resp = client.chat.completions.create(
                model=settings.rag.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            text = resp.choices[0].message.content.strip()
            # 尝试解析 JSON
            qa = json.loads(text)
            samples.append({
                "id": i + 1,
                "type": "generated",
                "question": qa.get("question", ""),
                "reference_answer": qa.get("answer", ""),
                "source_articles": [],
                "expected_chunk_ids": [],
                "source_content": chunk["chunk_content"],
            })
            logger.info(f"  生成 Q&A [{i+1}]：{qa.get('question', '')[:50]}...")
        except Exception as e:
            logger.warning(f"  第 {i+1} 个 chunk 生成失败: {e}")
            continue

    return samples


def main():
    parser = argparse.ArgumentParser(description="构建评估数据集")
    parser.add_argument("--knowledge_id", type=int, required=True, help="知识库 ID")
    parser.add_argument("--num_questions", type=int, default=30, help="生成问题数量")
    parser.add_argument("--output", type=str, default="scripts/eval_dataset.json", help="输出文件路径")
    args = parser.parse_args()

    logger.info(f"开始构建评估数据集: knowledge_id={args.knowledge_id}, num_questions={args.num_questions}")
    chunks = fetch_all_chunks(args.knowledge_id)
    if not chunks:
        logger.error("未读取到任何 chunks，退出")
        sys.exit(1)

    samples = generate_qa_pairs(chunks, args.num_questions)
    dataset = {
        "eval_dataset_name": f"知识库 {args.knowledge_id} 评估集 ({len(samples)} 条)",
        "document_id": args.knowledge_id,
        "knowledge_base_title": "",
        "samples": samples,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    logger.info(f"数据集已保存到 {args.output}，共 {len(samples)} 条")


if __name__ == "__main__":
    main()
