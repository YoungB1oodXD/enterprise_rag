"""
创建初始管理员用户

用法：
    python seed.py

首次运行会创建 admin / admin123 用户。
如果用户已存在则跳过。
"""
from app.core.logger import get_logger
from app.db.session import get_session
from app.db.models import User
from app.core.auth import hash_password

logger = get_logger(__name__)

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123"

with get_session() as session:
    existing = session.query(User).filter(User.username == DEFAULT_USERNAME).first()
    if existing:
        logger.info(f"用户 '{DEFAULT_USERNAME}' 已存在，跳过创建")
    else:
        user = User(
            username=DEFAULT_USERNAME,
            password_hash=hash_password(DEFAULT_PASSWORD),
        )
        session.add(user)
        session.commit()
        logger.info(f"用户 '{DEFAULT_USERNAME}' 创建成功（默认密码: {DEFAULT_PASSWORD}）")
