"""
VL (Vision-Language) 客户端：通过 DashScope VL API 描述图片内容。

用法：
  from app.utils.vl_client import describe_image
  description = describe_image(image_base64, "请描述这张图片的内容")
"""
import base64
from io import BytesIO
from openai import OpenAI

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_client = None


def _get_vl_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client
    _client = OpenAI(
        api_key=settings.rag.llm_api_key,
        base_url=settings.rag.llm_base_url,
    )
    return _client


def describe_image(image_bytes: bytes, prompt: str = "请详细描述这张图片的内容") -> str:
    """
    调用 VL 模型描述图片内容。
    失败时返回空字符串，不中断主流程。
    """
    if not settings.rag.llm_api_key:
        logger.warning("LLM API Key 未配置，跳过图片描述")
        return ""

    try:
        img_base64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{img_base64}"

        client = _get_vl_client()
        resp = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=300,
            temperature=0.1,
        )
        description = resp.choices[0].message.content.strip()
        logger.info(f"VL 图片描述完成 ({len(description)} 字)")
        return description
    except Exception as e:
        logger.warning(f"VL 图片描述失败: {e}")
        return ""
