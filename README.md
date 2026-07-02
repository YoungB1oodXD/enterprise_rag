# RAG Enterprise

> 企业级智能知识库问答系统 — 上传文档，智能问答，溯源可查。

RAG Enterprise 是一个面向企业知识库场景的 RAG（检索增强生成）问答平台。支持 PDF / Word / TXT / Markdown / CSV / Excel / JSON / JSONL 文档上传、后台自动解析、混合检索（BM25 + 向量 + RRF 融合 + Reranker 精排）、LLM 智能问答（含 SSE 流式输出）、引用溯源和离线评估。

![](https://img.shields.io/badge/Python-3.12-blue)
![](https://img.shields.io/badge/FastAPI-0.110-green)
![](https://img.shields.io/badge/React-18-61dafb)
![](https://img.shields.io/badge/Elasticsearch-8.x-orange)

---

## 功能特性

- **用户管理** — 用户注册/登录，JWT 认证，知识库级数据隔离，每个用户只能访问自己的数据
- **文档管理** — 上传 PDF / Word / TXT / Markdown / CSV / Excel / JSON / JSONL，后台自动解析，状态实时跟踪
- **文档预览** — 浏览器内直接预览 PDF 文档，支持大文件 Range 分片加载
- **智能分块** — PDF/Word 支持法规/制度类文档的章/节/条结构识别；TXT/Markdown 支持段落式分块；CSV/Excel/JSON/JSONL 支持记录级分块；超大 chunk 自动滑动窗口切分
- **表格提取** — PDF 解析时自动检测表格区域，以 Markdown 管道格式保留表格结构
- **图片理解** — PDF 中的图片自动提取并调用 VL 模型（qwen-vl-plus）描述内容，注入文本流
- **混合检索** — BM25 关键词 + dense_vector 语义向量双路召回，RRF 融合排序
- **Reranker 精排** — 百炼 gte-rerank-v2 API 对候选 chunk 二次打分，阈值过滤+保底策略确保召回质量
- **Query Rewrite** — 多轮对话中自动改写含指代/省略的问题；触发器条件判断减少无效调用；LRU 缓存避免重复改写
- **流式问答** — SSE 打字机效果，回答结束推送引用来源（文档名/页码/章节/chunk）
- **引用溯源** — 每段回答附带原文出处，支持核验
- **会话管理** — 多会话隔离，切换知识库自动切换会话列表，历史消息持久化，标题搜索+分页
- **多轮对话** — 保留对话历史，连续追问，首次对话自动生成会话标题
- **SQL 查询工具** — 通过自然语言触发数据库只读查询（统计、列表等），结果以 Markdown 表格返回，自动降级到 RAG
- **离线评估** — Top-K 对比、HitRate/MRR/Precision/Recall 多指标评估，支持 BM25/Vector/Hybrid 三种模式
- **RAGAS 标准化评估** — Faithfulness / Context Precision / Context Recall 自动化评测，按问题类型（精确条款/语义改写/场景/流程/多条款）分层分析
- **速率限制** — 内存中基于滑动窗口的速率限制器，防止 API 滥用
- **CI 质量门禁** — GitHub Actions 自动运行回归测试 + 每日全量评估，防止回归

---

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS |
| 数据库 | SQLite（开发）/ MySQL（生产），SQLAlchemy |
| 搜索引擎 | Elasticsearch 8.x（BM25 + dense_vector） |
| 文档解析 | pdfplumber（PDF，含表格+图片提取）、python-docx（Word）、openpyxl（Excel）、内置解析器（TXT/MD/CSV/JSON/JSONL），Tesseract OCR 兜底，qwen-vl-plus 图片描述 |
| Embedding | Sentence-Transformers / BGE（本地）或 DashScope text-embedding-v3（API） |
| Reranker | gte-rerank-v2（DashScope API） |
| 大模型 | OpenAI 兼容接口（通义千问 Qwen / DeepSeek） |
| 图片理解 | qwen-vl-plus 多模态模型（DashScope） |
| 认证 | JWT（HS256）+ bcrypt |
| 缓存 | LRU 缓存（TTL 支持），用于 embedding 向量和 Query Rewrite 结果 |
| 离线评估 | RAGAS（Faithfulness / Context Precision / Context Recall），HitRate/MRR 确定性指标 |
| 速限 | 滑动窗口内存速率限制器 |
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
│   ├── core/               # 配置、ES 客户端、日志、认证、速率限制
│   ├── db/                 # 数据库模型和会话管理
│   ├── api/                # 请求/响应数据模型
│   ├── services/           # 文档处理、问答服务
│   ├── retrieval/          # 检索、Query Rewrite
│   ├── evaluation/         # RAGAS 评估模块（指标、数据集、运行器）
│   ├── agent/              # Tool 系统（SQLQueryTool、ToolRegistry）
│   ├── models/             # Embedding / Reranker 模型管理
│   ├── utils/              # 文档解析、分块、VL 图片描述
│   ├── routers/            # 路由模块（auth, knowledge_base, document, conversation, chat, evaluation）
│   └── cache/              # LRU 缓存工具（TTL 支持）
├── frontend/               # React 前端
│   └── src/
│       ├── pages/          # 登录、知识库管理、Chat.tsx（独立问答页）
│       ├── components/     # 布局、路由守卫
│       ├── hooks/          # 认证、SSE 聊天（useChat）
│       └── api/            # HTTP 客户端（含 JWT）
├── docker/                 # Dockerfile + Nginx 配置
├── docker-compose.yml      # 一键部署
├── scripts/                # 离线评估脚本
│   ├── build_eval_dataset.py            # 从 ES 生成评估数据集
│   ├── evaluate_retrieval_only.py       # BM25/Vector/Hybrid 检索质量对比
│   ├── evaluate_with_topk.py            # Top-K 检索+生成对比评估
│   ├── run_ragas_eval.py                # RAGAS 标准化指标评测
│   ├── run_full_eval.py                 # 全量评估入口
│   └── seed_eval_ci.py                  # CI 环境数据种子
├── tests/                  # 测试
│   ├── test_eval_metrics.py             # 指标层单元测试
│   └── test_rag_regression.py           # LLM 回归测试
├── dataset/                # 评估数据集
├── config.yaml.example     # 配置模板
├── requirements-eval.txt   # 评估依赖
└── AGENTS.md               # 多智能体开发指南
```

---

## API 概览

| 端点 | 方法 | 说明 | 需认证 |
|------|------|------|--------|
| `/auth/login` | POST | 用户登录，返回 JWT | 否 |
| `/auth/register` | POST | 用户注册，自动返回 JWT | 否 |
| `/v1/knowledge_base` | POST | 创建知识库 | 是 |
| `/v1/knowledge_base/list` | GET | 知识库列表（按用户隔离） | 是 |
| `/v1/knowledge_base/{id}/documents` | GET | 文档列表 | 是 |
| `/v1/conversation/list` | GET | 会话列表（支持 `search` 标题模糊搜索 + `page`/`page_size` 分页） | 是 |
| `/v1/conversation` | POST | 创建新会话 | 是 |
| `/v1/conversation/{id}` | GET | 会话详情（含消息） | 是 |
| `/v1/conversation/{id}` | PUT | 重命名会话 | 是 |
| `/v1/conversation/{id}` | DELETE | 删除会话 | 是 |
| `/v1/document` | POST | 上传文档 | 是 |
| `/v1/document/{id}` | GET | 文档状态 | 是 |
| `/v1/document/{id}` | DELETE | 删除文档 | 是 |
| `/v1/document/{id}/file` | GET | 获取文档原始文件（支持 Range 请求） | 是 |
| `/v1/evaluation/run` | POST | 触发离线评估，返回指标报告 | 是 |
| `/v1/evaluation/reports` | GET | 历史评估报告 | 是 |
| `/chat` | POST | RAG 问答（含 Query Rewrite + Agent/Tool 路由） | 是 |
| `/chat/stream` | POST | 流式 RAG 问答（SSE，含 Agent/Tool 路由降级） | 是 |
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
