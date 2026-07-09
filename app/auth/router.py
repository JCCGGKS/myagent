from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import (
    ForgotPassword,
    ResetPassword,
    Token,
    UserInfo,
    UserLogin,
    UserRegister,
)
from app.auth.service import AuthError, forgot_password, login, register, reset_password
from app.db import SessionLocal, get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _db():
    """提供数据库会话；MySQL 未启用时返回 503。"""
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="数据库未启用")
    yield from get_db_session()


@router.post("/register", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
def api_register(data: UserRegister, db: Session = Depends(_db)) -> UserInfo:
    try:
        return register(data, db)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/login", response_model=Token)
def api_login(data: UserLogin, db: Session = Depends(_db)) -> Token:
    try:
        return login(data, db)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/forgot-password")
def api_forgot_password(data: ForgotPassword, db: Session = Depends(_db)) -> dict[str, str]:
    # 无论用户是否存在均返回成功（不泄露账号存在性）
    forgot_password(data, db)
    return {"detail": "若账号存在，重置链接已发送"}


@router.post("/reset-password")
def api_reset_password(data: ResetPassword, db: Session = Depends(_db)) -> dict[str, str]:
    try:
        reset_password(data, db)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"detail": "密码已重置"}


@router.get("/me", response_model=UserInfo)
def api_me(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    return user
