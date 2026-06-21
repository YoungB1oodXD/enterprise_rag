# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: RAG Enterprise

Full-stack enterprise RAG (Retrieval-Augmented Generation) Q&A system with React frontend, JWT authentication, hybrid search, and Docker Compose deployment.

## Commands

```bash
# 后端：安装依赖
pip install -r requirements.txt

# 后端：启动服务（先配置好 config.yaml 和 .env）
uvicorn main:app --host 0.0.0.0 --port 6006

# 后端：运行测试
pytest tests/ -v
pytest tests/test_demo.py -v -k test_name

# 后端：离线评估（先构建数据集，再跑评估）
python scripts/build_eval_dataset_with_source.py --knowledge_id 1 --num_questions 30 --output scripts/eval_dataset.json
python scripts/evaluate_retrieval_only.py --knowledge_id 1 --dataset scripts/eval_dataset.json --output scripts/result.json
python scripts/evaluate_with_topk.py --knowledge_id 1 --dataset scripts/eval_dataset.json --output scripts/result.json

# 后端：本地测试 Query Rewrite
python -m app.retrieval.query_rewriter

# 前端：安装依赖
cd frontend && npm install

# 前端：开发模式启动
cd frontend && npm run dev

# 前端：生产构建
cd frontend && npm run build

# Docker：一键启动
docker-compose up --build

# Docker：单独启动 ES（不启动其他服务）
docker-compose up elasticsearch
```

## Setup

1. `cp .env.example .env` and fill in `DASHSCOPE_API_KEY`
2. `cp config.yaml.example config.yaml` and configure ES host, model paths, LLM base_url
3. Start Elasticsearch via Docker: `docker-compose up elasticsearch` or build from `docker/Dockerfile.es` / `es-docker/Dockerfile`
4. `python seed.py` to create default admin user (admin / admin123)
5. Start backend: `uvicorn main:app --host 0.0.0.0 --port 6006`
6. Start frontend: `cd frontend && npm run dev`

## Architecture

```
main.py              FastAPI app, routes, exception handlers, auth
app/
├── core/
│   ├── config.py    YAML + env config, dataclass-typed singleton
│   ├── es_client.py Elasticsearch client singleton, index mappings
│   ├── auth.py      JWT token creation/validation, password hashing
│   └── logger.py    TimedRotatingFileHandler + stdout
├── db/
│   ├── models.py    SQLAlchemy ORM: User, KnowledgeBase, Document
│   └── session.py   Context-managed sessions, sqlite/mysql auto-detect
├── api/
│   └── schemas.py   Pydantic models: request/response, auth schemas
├── services/
│   ├── document_processor.py   Background pipeline: parse -> chunk -> embed -> ES bulk
│   └── qa_service.py           RAG pipeline: rewrite -> search -> prompt -> LLM -> sources
├── retrieval/
│   ├── searcher.py         hybrid_search (BM25 + vector) -> RRF -> Reranker
│   └── query_rewriter.py   Multi-turn query rewriting via LLM
├── models/
│   └── model_manager.py    Lazy-loaded embedding & reranker
└── utils/
    └── parser.py           PDF/Word parsing + chapter/section/article chunking

frontend/
├── src/
│   ├── pages/         Login, KnowledgeBases, KnowledgeBaseDetail
│   ├── components/    Layout, ProtectedRoute
│   ├── hooks/         useAuth, useChat (SSE streaming)
│   ├── api/           Axios client with JWT interceptor
│   └── store/         Auth context (localStorage token)
└── package.json       React + Vite + TypeScript + Tailwind CSS

docker/
├── Dockerfile.es         ES 8.5.3 + ik_max_word plugin
├── Dockerfile.backend    Python 3.12 + uvicorn
├── Dockerfile.frontend   Node build -> nginx static serve
└── nginx.conf            Reverse proxy /api to backend
```

## Key Design Decisions

- **Config**: `config.yaml` for all params; API keys from env vars (`DASHSCOPE_API_KEY` or `LLM_API_KEY`)
- **DB sessions**: Short-lived context managers — never hold a session across slow operations. Document processing uses two separate sessions to avoid SQLite write-lock contention
- **Model loading**: Lazy — first call to `get_embedding()` or `get_rerank_scores()` triggers load; service can start without models
- **Embedding mode**: Two modes auto-detected by config — API mode (DashScope text-embedding-v2 via OpenAI client) or local mode (Sentence-Transformer model). Switched by presence of `local_path` in `config.yaml`
- **LLM client**: Also lazy — first LLM call triggers OpenAI client init; import alone does not
- **Document chunking**: Regex-based for Chinese gov docs (第X章/第X节/第X条). `<<PAGE:N>>` markers track page numbers. Oversized chunks get sliding-window split
- **Retrieval**: BM25 + dense_vector dual recall -> RRF fusion -> optional BGE-Reranker re-ranking with confidence threshold
- **Query Rewrite**: LLM-based, only for multi-turn (len(user_messages) > 1). Falls back to original query on failure
- **Auth**: JWT (HS256) with bcrypt password hashing. Simple login-only flow. User data isolated by `user_id`
- **Frontend dev proxy**: Vite proxies `/v1`, `/chat`, `/auth`, `/health` to backend at `localhost:6006` — no CORS issues in dev
- **SSE streaming**: `/chat/stream` returns `data: {"chunk":"..."}\n\n` events, ends with `data: [DONE]\n\n`, then a final event with `{"sources": [...]}`
- **DB stores** only metadata; actual content + vectors live in ES `chunk_info` and `document_meta` indices
- **Deletion cascade**: Delete document -> delete ES chunks (delete_by_query) -> delete DB record -> delete file

## ES Dependencies

- Elasticsearch 8.x with `ik_max_word` analyzer plugin
- Start via Docker: `docker/Dockerfile.es`, `es-docker/Dockerfile`, or `docker-compose.yml`
