from __future__ import annotations

from app.schema.auth import (
    ChangePassword,
    ForgotPassword,
    LoginResponse,
    ResetPassword,
    UserInfo,
    UserLogin,
    UserRegister,
)
from app.dao import UserDAO
from app.pkgs.auth import (
    create_access_token,
    create_reset_token,
    decode_token,
    hash_password,
    send_reset_email,
    verify_password,
)
from app.utils import log_error, log_info, log_warning


class AuthError(Exception):
    """认证业务错误，携带 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def register(data: UserRegister, user_dao: UserDAO) -> UserInfo:
    """开放注册：校验用户名/邮箱唯一后写入。"""
    if await user_dao.get_by_username(data.username) is not None:
        log_warning("auth", "register username_exists username=%s", data.username)
        raise AuthError("用户名已存在", status_code=409)
    if await user_dao.get_by_email(data.email) is not None:
        log_warning("auth", "register email_exists email=%s", data.email)
        raise AuthError("邮箱已注册", status_code=409)

    user = await user_dao.create(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    log_info("auth", "register success user_id=%s username=%s", user["id"], user["username"])
    return UserInfo(id=user["id"], username=user["username"], email=user["email"])


async def login(data: UserLogin, user_dao: UserDAO) -> LoginResponse:
    """校验用户名与密码，成功返回 access token 及用户信息。"""
    user = await user_dao.get_by_username(data.username)
    if user is None or not verify_password(data.password, user["password_hash"]):
        log_warning("auth", "login failed username=%s reason=%s", data.username, "not_found_or_bad_password")
        raise AuthError("用户名或密码错误", status_code=401)
    token = create_access_token(user["id"], user["username"], user["email"])
    log_info("auth", "login success user_id=%s username=%s", user["id"], user["username"])
    return LoginResponse(
        access_token=token,
        user=UserInfo(id=user["id"], username=user["username"], email=user["email"]),
    )


async def forgot_password(data: ForgotPassword, user_dao: UserDAO) -> None:
    """找回密码：邮箱未注册直接报错，已注册则签发 reset token 并发送邮件。"""
    user = await user_dao.get_by_email(data.email)
    if user is None:
        log_warning("auth", "forgot_password email_not_registered email=%s", data.email)
        raise AuthError("邮箱地址未注册", status_code=404)
    try:
        reset_token = create_reset_token(user["id"], user["email"])
        send_reset_email(user["email"], reset_token)
    except Exception as exc:
        log_error(
            "auth",
            "forgot_password send_email_failed user_id=%s email=%s err=%r",
            user["id"],
            user["email"],
            exc,
        )
        raise
    log_info("auth", "forgot_password sent user_id=%s email=%s", user["id"], user["email"])


async def reset_password(data: ResetPassword, user_dao: UserDAO) -> None:
    """凭 reset token 重置密码。"""
    try:
        payload = decode_token(data.token, expected_purpose="reset")
    except Exception as exc:  # noqa: BLE001
        log_warning("auth", "reset_password invalid_token err=%r", exc)
        raise AuthError(f"重置凭证无效: {exc}", status_code=400) from exc

    user_id = payload.get("user_id")
    user = await user_dao.get_by_id(user_id)
    if user is None:
        log_warning("auth", "reset_password user_not_found user_id=%s", user_id)
        raise AuthError("用户不存在", status_code=404)

    await user_dao.update_password(user_id, hash_password(data.new_password))
    log_info("auth", "reset_password success user_id=%s", user_id)


async def change_password(user_id: int, data: ChangePassword, user_dao: UserDAO) -> None:
    """登录用户修改密码：验证旧密码后设新密码。"""
    user = await user_dao.get_by_id(user_id)
    if user is None:
        log_warning("auth", "change_password user_not_found user_id=%s", user_id)
        raise AuthError("用户不存在", status_code=404)
    if not verify_password(data.old_password, user["password_hash"]):
        log_warning("auth", "change_password wrong_old_password user_id=%s", user_id)
        raise AuthError("原密码错误", status_code=400)
    await user_dao.update_password(user_id, hash_password(data.new_password))
    log_info("auth", "change_password success user_id=%s", user_id)
