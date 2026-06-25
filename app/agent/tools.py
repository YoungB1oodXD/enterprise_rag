"""
Tool 定义：可被 LLM 调用的工具。

当前工具：
  - SQLQueryTool: 只读 SQL 查询，返回 Markdown 表格
"""
import traceback
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List

from app.core.logger import get_logger

logger = get_logger(__name__)


class BaseTool:
    """工具基类。子类需要定义 name / description / parameters 并实现 execute。"""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def execute(self, params: Dict[str, Any]) -> str:
        raise NotImplementedError


class SQLQueryTool(BaseTool):
    name = "sql_query"
    description = "对知识库系统的数据库执行只读 SQL 查询，返回 Markdown 表格。仅允许 SELECT 语句。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "只读 SELECT SQL 查询语句",
            }
        },
        "required": ["query"],
    }

    _timeout = 10  # 秒
    _max_rows = 20

    # 允许查询的表（白名单）
    _allowed_tables = {"user", "knowledge_base", "document", "conversation", "conversation_message"}

    def execute(self, params: Dict[str, Any]) -> str:
        raw_query = params.get("query", "").strip()
        if not raw_query:
            return "错误：SQL 查询为空。"

        # ── 安全检查 ────────────────────────────────────────────
        upper = raw_query.upper().strip()
        if not upper.startswith("SELECT"):
            return "错误：仅允许 SELECT 查询。"
        if re.search(r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|REPLACE|EXEC|CALL|--|/\*)", upper):
            return "错误：查询包含不安全的 SQL 关键字。"

        # 提取表名做基本白名单检查
        table_matches = re.findall(r"\bFROM\s+(\w+)\b|\bJOIN\s+(\w+)\b", upper)
        mentioned_tables = set(t for pair in table_matches for t in pair if t)
        unknown = mentioned_tables - self._allowed_tables
        if unknown:
            return f"错误：不允许查询表 {', '.join(sorted(unknown))}。允许的表：{', '.join(sorted(self._allowed_tables))}"

        # ── 执行查询 ────────────────────────────────────────────
        try:
            from app.db.session import _engine as engine
            from sqlalchemy import text

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._run_query, engine, raw_query)
                rows, columns = future.result(timeout=self._timeout)
        except FuturesTimeout:
            logger.warning("SQL 查询超时")
            return "错误：查询执行超时（10 秒）。"
        except Exception as e:
            logger.warning(f"SQL 查询执行失败: {e}")
            return f"错误：查询执行失败 — {e}"

        # ── 格式化结果 ──────────────────────────────────────────
        if not rows:
            return "查询结果为空。"

        md = "| " + " | ".join(columns) + " |\n"
        md += "| " + " | ".join("---" for _ in columns) + " |\n"
        for row in rows[: self._max_rows]:
            md += "| " + " | ".join(str(v) if v is not None else "" for v in row) + " |\n"

        if len(rows) > self._max_rows:
            md += f"\n*（共 {len(rows)} 行，仅显示前 {self._max_rows} 行）*"

        return md

    @staticmethod
    def _run_query(engine, raw_query: str):
        from sqlalchemy import text

        with engine.connect() as conn:
            result = conn.execute(text(raw_query))
            columns = list(result.keys())
            rows = [list(row) for row in result.fetchall()]
        return rows, columns
