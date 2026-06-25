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


# ── 关键词路由 ────────────────────────────────────────────────────
# 触发 SQL 工具的关键词
_SQL_TRIGGERS = [
    "统计", "多少个", "数量", "几条", "多少条", "总数",
    "列出", "列表", "有哪些", "分别",
    " count ", " count(", "select ", "查询",
]


def auto_route(query: str) -> Optional[str]:
    """
    判断是否需要调用工具。返回匹配的工具名，或 None。
    """
    q = query.lower().strip()

    # SQL 工具触发
    for keyword in _SQL_TRIGGERS:
        if keyword.lower() in q:
            logger.info(f"关键词 '{keyword}' 触发 SQL 工具路由")
            return "sql_query"

    return None
