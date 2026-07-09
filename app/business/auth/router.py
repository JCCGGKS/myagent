from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.business.auth.deps import get_current_user
from app.business.auth.models import (
    ForgotPassword,
    ResetPassword,
    Token,
    UserInfo,
    UserLogin,
    UserRegister,
)
from app.business.auth.service import AuthError, forgot_password, login, register, reset_password
from app.dao import UserDAO, get_user_dao

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
def api_register(data: UserRegister, user_dao: UserDAO = Depends(get_user_dao)) -> UserInfo:
    try:
        return register(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/login", response_model=Token)
def api_login(data: UserLogin, user_dao: UserDAO = Depends(get_user_dao)) -> Token:
    try:
        return login(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/forgot-password")
def api_forgot_password(data: ForgotPassword, user_dao: UserDAO = Depends(get_user_dao)) -> dict[str, str]:
    # 无论用户是否存在均返回成功（不泄露账号存在性）
    forgot_password(data, user_dao)
    return {"detail": "若账号存在，重置链接已发送"}


@router.post("/reset-password")
def api_reset_password(data: ResetPassword, user_dao: UserDAO = Depends(get_user_dao)) -> dict[str, str]:
    try:
        reset_password(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"detail": "密码已重置"}


@router.get("/me", response_model=UserInfo)
def api_me(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    return user
