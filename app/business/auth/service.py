from __future__ import annotations

from app.business.auth.models import (
    ForgotPassword,
    ResetPassword,
    Token,
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


class AuthError(Exception):
    """认证业务错误，携带 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def register(data: UserRegister, user_dao: UserDAO) -> UserInfo:
    """开放注册：校验用户名/邮箱唯一后写入。"""
    if user_dao.get_by_username(data.username) is not None:
        raise AuthError("用户名已存在", status_code=409)
    if user_dao.get_by_email(data.email) is not None:
        raise AuthError("邮箱已注册", status_code=409)

    user = user_dao.create(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    return UserInfo(id=user["id"], username=user["username"], email=user["email"])


def login(data: UserLogin, user_dao: UserDAO) -> Token:
    """校验用户名与密码，成功返回 access token。"""
    user = user_dao.get_by_username(data.username)
    if user is None or not verify_password(data.password, user["password_hash"]):
        raise AuthError("用户名或密码错误", status_code=401)
    token = create_access_token(user["id"], user["username"], user["email"])
    return Token(access_token=token)


def forgot_password(data: ForgotPassword, user_dao: UserDAO) -> None:
    """找回密码：用户存在才签发 reset token 并发送邮件。"""
    user = user_dao.get_by_email(data.email)
    if user is None:
        return
    reset_token = create_reset_token(user["id"], user["email"])
    send_reset_email(user["email"], reset_token)


def reset_password(data: ResetPassword, user_dao: UserDAO) -> None:
    """凭 reset token 重置密码。"""
    try:
        payload = decode_token(data.token, expected_purpose="reset")
    except Exception as exc:  # noqa: BLE001
        raise AuthError(f"重置凭证无效: {exc}", status_code=400) from exc

    user_id = int(payload.get("user_id"))
    user = user_dao.get_by_id(user_id)
    if user is None:
        raise AuthError("用户不存在", status_code=404)

    user_dao.update_password(user_id, hash_password(data.new_password))
