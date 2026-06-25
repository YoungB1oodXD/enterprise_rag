import time
from fastapi import APIRouter, HTTPException
from app.db.session import get_session
from app.db.models import User
from app.api.schemas import LoginRequest, RegisterRequest, LoginResponse
from app.core.auth import verify_password, hash_password, create_access_token

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", summary="用户登录")
def login(req: LoginRequest):
    start_time = time.time()
    with get_session() as session:
        user = session.query(User).filter(User.username == req.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        token = create_access_token(data={"sub": str(user.id)})
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            username=user.username,
        )


@router.post("/register", summary="用户注册")
def register(req: RegisterRequest):
    start_time = time.time()
    with get_session() as session:
        existing = session.query(User).filter(User.username == req.username).first()
        if existing:
            raise HTTPException(status_code=409, detail="用户名已存在")

        user = User(
            username=req.username,
            password_hash=hash_password(req.password),
        )
        session.add(user)
        session.flush()

        token = create_access_token(data={"sub": str(user.id)})
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            username=user.username,
        )
