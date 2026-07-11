from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schema.auth import (
    ChangePassword,
    ForgotPassword,
    LoginResponse,
    ResetPassword,
    UserInfo,
    UserLogin,
    UserRegister,
)
from app.business.auth.service import (
    AuthError,
    change_password,
    forgot_password,
    login,
    register,
    reset_password,
)
from app.dao import UserDAO, get_user_dao

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
async def api_register(data: UserRegister, user_dao: UserDAO = Depends(get_user_dao)) -> UserInfo:
    try:
        return await register(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/login", response_model=LoginResponse)
async def api_login(data: UserLogin, user_dao: UserDAO = Depends(get_user_dao)) -> LoginResponse:
    try:
        return await login(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/forgot-password")
async def api_forgot_password(data: ForgotPassword, user_dao: UserDAO = Depends(get_user_dao)) -> dict[str, str]:
    """找回密码：邮箱未注册返回 404，已注册则发送重置链接。"""
    try:
        await forgot_password(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"detail": "重置链接已发送"}


@router.post("/reset-password")
async def api_reset_password(data: ResetPassword, user_dao: UserDAO = Depends(get_user_dao)) -> dict[str, str]:
    try:
        await reset_password(data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"detail": "密码已重置"}


@router.post("/change-password")
async def api_change_password(
    data: ChangePassword,
    request: Request,
    user_dao: UserDAO = Depends(get_user_dao),
) -> dict[str, str]:
    """登录用户修改密码（需 Authorization 头，由 AuthMiddleware 鉴权）。"""
    try:
        await change_password(request.state.user.id, data, user_dao)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"detail": "密码已修改"}
