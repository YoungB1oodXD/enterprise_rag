"""
CI 环境数据种子

从评估数据集 JSON 直接构造 ES 文档和 chunk，
无需真实文件上传 + 解析，使 CI 环境可运行检索评估。

用法：
  python scripts/seed_eval_ci.py

环境变量：
  ES_HOST (默认 localhost)
  ES_PORT (默认 9200)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.logger import get_logger
from app.core.es_client import es

logger = get_logger(__name__)

# ES 连接参数
ES_HOST = os.getenv("ES_HOST", "localhost")
ES_PORT = os.getenv("ES_PORT", "9200")
ES_URL = f"http://{ES_HOST}:{ES_PORT}"

# 数据集路径（按优先级尝试多个路径）
DATASET_CANDIDATES = [
    "dataset/eval_dataset_ip_customs_balanced_30.json",
    "dataset/eval_dataset_ip_customs_answerable_27.json",
]

KNOWLEDGE_ID = 1
DOCUMENT_ID = 1
INDEX_DOC = settings.es.index_document_meta
INDEX_CHUNK = settings.es.index_chunk_info


def _wait_for_es(timeout: int = 60):
    """等待 ES 就绪"""
    import urllib.request

    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"{ES_URL}/_cluster/health", timeout=5)
            if resp.status == 200:
                logger.info("ES 已就绪")
                return True
        except Exception:
            pass
        logger.info("等待 ES 就绪...")
        time.sleep(3)
    raise RuntimeError(f"ES 在 {timeout}s 内未就绪")


def _ensure_index(index: str, mappings: dict = None):
    """确保索引存在，不存在则创建"""
    if not es.indices.exists(index=index):
        body = {}
        if mappings:
            body["mappings"] = mappings
        es.indices.create(index=index, body=body)
        logger.info(f"创建索引: {index}")
    else:
        logger.info(f"索引已存在: {index}")


def seed_data():
    """从数据集 JSON 构造 ES 文档并写入"""
    _wait_for_es()

    # 查找数据集
    dataset_path = None
    for candidate in DATASET_CANDIDATES:
        full_path = os.path.join(os.path.dirname(__file__), "..", candidate)
        if os.path.exists(full_path):
            dataset_path = full_path
            break
    if not dataset_path:
        logger.error(f"未找到数据集，尝试路径: {DATASET_CANDIDATES}")
        sys.exit(1)

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    samples = dataset.get("samples", [])
    knowledge_base_title = dataset.get("knowledge_base_title", "法律法规")
    logger.info(f"加载数据集: {dataset_path} ({len(samples)} 条)")

    # 收集所有引用的条号
    all_articles = set()
    for s in samples:
        for art in s.get("source_articles", []):
            all_articles.add(art)

    logger.info(f"共引用 {len(all_articles)} 个条号: {sorted(all_articles)}")

    # 确保索引存在
    _ensure_index(INDEX_DOC)
    _ensure_index(INDEX_CHUNK)

    # 1. 写入文档元数据
    doc_body = {
        "knowledge_id": KNOWLEDGE_ID,
        "title": f"CI 种子文档 - {knowledge_base_title}",
        "file_name": "ci_seed_doc.txt",
        "file_size": 0,
        "page_count": 0,
        "status": "completed",
    }
    try:
        es.index(index=INDEX_DOC, id=DOCUMENT_ID, body=doc_body, refresh="wait_for")
        logger.info(f"写入文档元数据: id={DOCUMENT_ID}")
    except Exception as e:
        logger.warning(f"文档元数据写入失败 (可能已存在): {e}")

    # 2. 构造并写入 chunk
    chunk_id = 0
    for art in sorted(all_articles):
        chunk_id += 1
        chunk_body = {
            "knowledge_id": KNOWLEDGE_ID,
            "document_id": DOCUMENT_ID,
            "chunk_content": f"第{art}条 知识产权海关保护条例相关规定",
            "breadcrumb": f"知识产权海关保护条例 > 第{art}条",
            "embedding_vector": None,
        }
        try:
            es.index(index=INDEX_CHUNK, id=chunk_id, body=chunk_body, refresh="wait_for")
        except Exception as e:
            logger.error(f"chunk 写入失败 (id={chunk_id}): {e}")

    logger.info(f"CI 数据种子完成: 写入 {chunk_id} 个 chunk")


if __name__ == "__main__":
    seed_data()
