from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.email import send_reset_email
from app.auth.jwt import create_access_token, create_reset_token, decode_token
from app.auth.models import ForgotPassword, ResetPassword, Token, UserLogin, UserRegister, UserInfo
from app.auth.password import hash_password, verify_password
from app.db.models import User


class AuthError(Exception):
    """认证业务错误，携带 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def register(data: UserRegister, db: Session) -> UserInfo:
    """开放注册：校验用户名/邮箱唯一后写入。"""
    existing = (
        db.query(User)
        .filter((User.username == data.username) | (User.email == data.email))
        .first()
    )
    if existing is not None:
        if existing.username == data.username:
            raise AuthError("用户名已存在", status_code=409)
        raise AuthError("邮箱已注册", status_code=409)

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserInfo(id=user.id, username=user.username, email=user.email)


def login(data: UserLogin, db: Session) -> Token:
    """校验用户名与密码，成功返回 access token。"""
    user = db.query(User).filter(User.username == data.username).first()
    if user is None or not verify_password(data.password, user.password_hash):
        raise AuthError("用户名或密码错误", status_code=401)
    token = create_access_token(user.id, user.username, user.email)
    return Token(access_token=token)


def forgot_password(data: ForgotPassword, db: Session) -> None:
    """找回密码：用户存在才签发 reset token 并发送邮件。

    为不泄露账号存在性，无论用户是否存在都返回成功（模糊处理）。
    """
    user = db.query(User).filter(User.email == data.email).first()
    if user is None:
        return
    reset_token = create_reset_token(user.id, user.email)
    send_reset_email(user.email, reset_token)


def reset_password(data: ResetPassword, db: Session) -> None:
    """凭 reset token 重置密码。"""
    try:
        payload = decode_token(data.token, expected_purpose="reset")
    except Exception as exc:  # noqa: BLE001
        raise AuthError(f"重置凭证无效: {exc}", status_code=400) from exc

    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AuthError("用户不存在", status_code=404)

    user.password_hash = hash_password(data.new_password)
    db.commit()
