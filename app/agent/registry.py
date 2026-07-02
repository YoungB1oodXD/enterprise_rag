"""
Tool 注册和自动路由。

ToolRegistry（单例）：管理所有可用工具。
auto_route(query)：关键词匹配判断是否需要调用工具。
"""
from typing import Dict, List, Optional

from app.agent.tools import BaseTool, SQLQueryTool
from app.core.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册中心（单例）。"""

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
            cls._instance._initialized = False
        return cls._instance

    def initialize(self) -> None:
        if self._initialized:
            return
        self.register(SQLQueryTool())
        self._initialized = True
        logger.info("工具注册完成，可用工具：{}".format(", ".join(self._tools.keys())))

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"注册工具: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_openai_tools(self) -> List[Dict]:
        """返回 OpenAI function-calling 格式的工具列表。"""
        result = []
        for tool in self._tools.values():
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return result


# ── 关键词路由（第一道闸）─────────────────────────────────────────
#
# 设计原则：
# 只有明确涉及数据库表记录的问题才走 SQL 工具。
# 知识库内容问题（法规、政策等）必须走 RAG 检索，不能被 SQL 劫持。
#
# 第一道闸：快速关键词匹配
# 仅保留明确的 SQL 语法关键词，中文自然语言触发词容易误伤。
_SQL_DIRECT_TRIGGERS = [
    " count(", " select ", "select ",  # SQL 语法
    # 注意：中文关键词如 "统计"/"列出"/"有哪些"/"查询" 等已在测试中发现
    # 大量误判（如 "有哪些情形海关不予备案" → 被 SQL 拦截），
    # 已移除。这类问题由 RAG 流程处理。
]


def auto_route(query: str) -> Optional[str]:
    """
    第一道路由：快速关键词匹配。
    仅在查询包含明确的 SQL 语法关键词时触发。
    返回匹配的工具名，或 None。

    返回 None 后，第二道 LLM 语义路由（_try_tool_route 内）会处理剩余情况。
    """
    q = query.lower().strip()

    for keyword in _SQL_DIRECT_TRIGGERS:
        if keyword.lower() in q:
            logger.info(f"关键词 '{keyword}' 触发 SQL 工具路由")
            return "sql_query"

    return None
