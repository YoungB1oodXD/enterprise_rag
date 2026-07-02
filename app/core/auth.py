"""
JWT 认证模块

提供：
- create_access_token() 创建 JWT
- get_current_user() FastAPI 依赖注入，从请求中提取当前用户
- hash_password() / verify_password() 密码哈希与验证
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.db.session import get_session
from app.db.models import User

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY 未设置！请在 .env 文件中配置 JWT_SECRET_KEY。\n"
        "示例：openssl rand -hex 32"
    )
SECRET_KEY = JWT_SECRET_KEY
ALGORITHM = "HS256"
_jwt_expire_str = os.getenv("JWT_EXPIRE_MINUTES", "60")
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(_jwt_expire_str)
except ValueError:
    logging.warning("JWT_EXPIRE_MINUTES 格式无效: '%s'，使用默认值 60 分钟", _jwt_expire_str)
    ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """FastAPI 依赖注入：从 Bearer token 或 ?token= 查询参数解析出当前用户"""
    token = credentials.credentials if credentials else None
    if not token:
        token = request.query_params.get("token")
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = int(payload.get("sub"))
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if user is None:
            raise credentials_exception
        return user
