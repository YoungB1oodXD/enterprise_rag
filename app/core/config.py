# app/core/config.py
"""
配置加载模块

设计原则：
1. 所有配置从 config.yaml 读取，敏感信息（API Key）从环境变量读取
2. 用 dataclass 做类型约束，避免到处用 config["xxx"]["xxx"] 裸字符串
3. 单例模式：整个进程只加载一次配置
"""
import os
import yaml
import warnings
from dataclasses import dataclass, field
from typing import Dict
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent.parent


def _load_yaml() -> dict:
    config_path = BASE_DIR / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class AppConfig:
    host: str
    port: int
    debug: bool


@dataclass
class ESConfig:
    host: str
    port: int
    scheme: str
    username: str
    password: str
    index_document_meta: str
    index_chunk_info: str


@dataclass
class DatabaseConfig:
    engine: str
    host: str = "localhost"
    port: int = 3306
    username: str = ""
    password: str = ""
    db_name: str = ""
    path: str = "rag.db"


@dataclass
class RAGConfig:
    embedding_model: str
    use_rerank: bool
    rerank_model: str
    chunk_size: int
    chunk_overlap: int
    bm25_top_k: int
    vector_top_k: int
    rrf_k: int
    rerank_top_k: int
    confidence_threshold: float
    llm_base_url: str
    llm_model: str
    llm_temperature: float
    llm_top_p: float
    llm_max_tokens: int
    min_rerank_top_k: int = 3
    llm_api_key: str = field(default="")


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class Settings:
    app: AppConfig
    es: ESConfig
    db: DatabaseConfig
    rag: RAGConfig
    logging: LoggingConfig
    device: str
    base_dir: Path
    embedding_model_params: Dict
    rerank_model_params: Dict


def _auto_detect_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _validate_model_paths(s: Settings) -> None:
    embed_params = s.embedding_model_params.get(s.rag.embedding_model, {})
    if "local_path" in embed_params:
        embed_path = embed_params["local_path"]
        if not Path(embed_path).exists():
            warnings.warn(
                f"Embedding模型路径不存在：{embed_path}\n"
                f"请检查 config.yaml 里的 models.embedding.{s.rag.embedding_model}.local_path",
                stacklevel=2
            )


def _build_settings() -> Settings:
    raw = _load_yaml()
    rag_raw = raw["rag"]

    llm_api_key = os.getenv("DASHSCOPE_API_KEY", os.getenv("LLM_API_KEY", ""))

    if not llm_api_key:
        warnings.warn(
            "环境变量 DASHSCOPE_API_KEY 未设置，LLM 和 Embedding 相关接口将无法使用。\n"
            "在项目根目录 .env 文件写入：DASHSCOPE_API_KEY=your-key",
            stacklevel=2
        )

    device = raw.get("device", "auto")
    if device == "auto":
        device = _auto_detect_device()

    rerank_model_params = raw.get("models", {}).get("rerank", {})

    # ES 密码支持从环境变量覆盖（优先级高于 config.yaml）
    es_raw = dict(raw["elasticsearch"])
    es_raw["password"] = os.getenv("ES_PASSWORD", es_raw["password"])

    # 数据库密码支持从环境变量覆盖
    db_raw = dict(raw["database"])
    db_raw["password"] = os.getenv("DB_PASSWORD", db_raw["password"])

    result = Settings(
        app=AppConfig(**raw["app"]),
        es=ESConfig(**es_raw),
        db=DatabaseConfig(**db_raw),
        rag=RAGConfig(
            embedding_model=rag_raw["embedding_model"],
            use_rerank=rag_raw.get("use_rerank", False),
            rerank_model=rag_raw.get("rerank_model", ""),
            chunk_size=rag_raw["chunk_size"],
            chunk_overlap=rag_raw["chunk_overlap"],
            bm25_top_k=rag_raw["bm25_top_k"],
            vector_top_k=rag_raw["vector_top_k"],
            rrf_k=rag_raw["rrf_k"],
            rerank_top_k=rag_raw["rerank_top_k"],
            confidence_threshold=rag_raw["confidence_threshold"],
            min_rerank_top_k=rag_raw.get("min_rerank_top_k", 3),
            llm_base_url=rag_raw["llm_base_url"],
            llm_model=rag_raw["llm_model"],
            llm_temperature=rag_raw["llm_temperature"],
            llm_top_p=rag_raw["llm_top_p"],
            llm_max_tokens=rag_raw["llm_max_tokens"],
            llm_api_key=llm_api_key,
        ),
        logging=LoggingConfig(**raw["logging"]),
        device=device,
        base_dir=BASE_DIR,
        embedding_model_params=raw["models"]["embedding"],
        rerank_model_params=rerank_model_params,
    )

    _validate_model_paths(result)
    return result


settings = _build_settings()