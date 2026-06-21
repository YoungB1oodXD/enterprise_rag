# RAG Enterprise

> 企业级智能知识库问答系统 — 上传文档，智能问答，溯源可查。

RAG Enterprise 是一个面向企业知识库场景的 RAG（检索增强生成）问答平台。支持 PDF/Word 文档上传、后台自动解析、混合检索（BM25 + 向量 + RRF 融合 + Reranker 精排）、LLM 智能问答（含 SSE 流式输出）、引用溯源和离线评估。

![](https://img.shields.io/badge/Python-3.12-blue)
![](https://img.shields.io/badge/FastAPI-0.110-green)
![](https://img.shields.io/badge/React-18-61dafb)
![](https://img.shields.io/badge/Elasticsearch-8.x-orange)

---

## 功能特性

- **文档管理** — 上传 PDF/Word，后台自动解析，状态实时跟踪
- **智能分块** — 针对法规/制度类文档的章/节/条结构识别，保留语义边界
- **混合检索** — BM25 关键词 + dense_vector 语义向量双路召回，RRF 融合排序
- **Reranker 精排** — 可选 BGE-Reranker 对候选 chunk 二次打分，过滤低相关结果
- **Query Rewrite** — 多轮对话中自动改写含指代/省略的问题，提升检索准确率
- **流式问答** — SSE 打字机效果，回答结束推送引用来源（文档名/页码/章节/chunk）
- **引用溯源** — 每段回答附带原文出处，支持核验
- **多轮对话** — 保留对话历史，连续追问
- **离线评估** — Top-K / MRR / RAGAS (Faithfulness, Answer Relevancy) 多维度评估
- **用户认证** — JWT 登录，知识库级别的数据隔离

---

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS |
| 数据库 | SQLite（开发）/ MySQL（生产），SQLAlchemy |
| 搜索引擎 | Elasticsearch 8.x（BM25 + dense_vector） |
| 文档解析 | pdfplumber、pytesseract OCR、python-docx |
| Embedding | Sentence-Transformers / BGE |
| Reranker | BGE-Reranker / Cross-Encoder |
| 大模型 | OpenAI 兼容接口（通义千问 / DeepSeek / OpenAI） |
| 认证 | JWT（HS256）+ bcrypt |
| 部署 | Docker Compose |

---

## 快速开始

### 前置要求

- Python 3.12+
- Node.js 20+
- Elasticsearch 8.x（with ik 分词器）
- （可选）Docker & Docker Compose

### 1. 配置

```bash
# 环境变量（API Key）
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

# 项目配置
cp config.yaml.example config.yaml
# 编辑 config.yaml，配置 ES 地址、模型路径、LLM base_url
```

### 2. 初始化

```bash
# 安装后端依赖
pip install -r requirements.txt

# 创建初始用户
python seed.py

# 启动后端
uvicorn main:app --host 0.0.0.0 --port 6006
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，使用 `admin / admin123` 登录。

---

## 项目结构

```
rag_enterprise/
├── main.py                 # FastAPI 应用入口
├── app/                    # 后端 Python 包
│   ├── core/               # 配置、ES 客户端、日志、认证
│   ├── db/                 # 数据库模型和会话管理
│   ├── api/                # 请求/响应数据模型
│   ├── services/           # 文档处理、问答服务
│   ├── retrieval/          # 检索、Query Rewrite
│   ├── models/             # Embedding / Reranker 模型管理
│   └── utils/              # 文档解析、分块
├── frontend/               # React 前端
│   └── src/
│       ├── pages/          # 登录、知识库管理、聊天
│       ├── components/     # 布局、路由守卫
│       ├── hooks/          # 认证、SSE 聊天
│       └── api/            # HTTP 客户端（含 JWT）
├── docker/                 # Dockerfile + Nginx 配置
├── docker-compose.yml      # 一键部署
├── scripts/                # 评估脚本
└── tests/                  # 测试
```

---

## API 概览

| 端点 | 方法 | 说明 | 需认证 |
|------|------|------|--------|
| `/auth/login` | POST | 用户登录，返回 JWT | 否 |
| `/v1/knowledge_base` | POST | 创建知识库 | 是 |
| `/v1/knowledge_base/{id}/documents` | GET | 文档列表 | 是 |
| `/v1/document` | POST | 上传文档 | 是 |
| `/v1/document/{id}` | GET | 文档状态 | 是 |
| `/v1/document/{id}` | DELETE | 删除文档 | 是 |
| `/chat` | POST | RAG 问答 | 是 |
| `/chat/stream` | POST | 流式 RAG 问答（SSE） | 是 |
| `/health` | GET | 健康检查 | 否 |

---

## 检索策略对比

| 策略 | Top-1 | Top-3 | MRR | 平均耗时 |
|------|------:|------:|----:|--------:|
| BM25 | 81.48% | 92.59% | 0.8778 | 48ms |
| Hybrid + RRF | 81.48% | 92.59% | 0.8704 | 298ms |
| **Hybrid + RRF + Reranker** | **88.89%** | **100%** | **0.9383** | 2250ms |

> 详细评估数据见 `docs/`

---

## 相关文档

- [架构设计](docs/architecture.md)
- [评估数据集说明](docs/EVAL_DATASET_README.md)
- [评估脚本使用](docs/README_evaluation_snippet.md)

---

## License

MIT
