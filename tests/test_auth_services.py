from __future__ import annotations

import asyncio

from app.schema.auth import ForgotPassword, ResetPassword, UserLogin, UserRegister
from app.business.auth.service import (
    AuthError,
    forgot_password,
    login,
    register,
    reset_password,
)
from app.dao import SqlUserDAO
from app.model import user  # noqa: F401  (确保 User 表注册到 Base.metadata)
from app.pkgs.auth import (
    create_access_token,
    create_reset_token,
    decode_token,
    hash_password,
    verify_password,
)
from conftest import make_async_session_factory


def make_user_dao():
    """M2：SqlUserDAO 使用 AsyncSession，注入异步会话工厂（内存 SQLite）。"""
    return SqlUserDAO(make_async_session_factory())


def test_password_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_register_and_login_and_token():
    user_dao = make_user_dao()
    user = asyncio.run(
        register(UserRegister(username="alice", email="a@x.com", password="pw123456"), user_dao)
    )
    assert user.username == "alice"

    token = asyncio.run(login(UserLogin(username="alice", password="pw123456"), user_dao))
    assert token.access_token

    payload = decode_token(token.access_token, expected_purpose="access")
    assert payload["user_id"] == user.id
    assert payload["username"] == "alice"
    assert payload["email"] == "a@x.com"


def test_duplicate_register_conflicts():
    user_dao = make_user_dao()
    asyncio.run(register(UserRegister(username="bob", email="b@x.com", password="pw123456"), user_dao))
    try:
        asyncio.run(
            register(UserRegister(username="bob", email="other@x.com", password="pw123456"), user_dao)
        )
    except AuthError as e:
        assert e.status_code == 409
    else:
        raise AssertionError("应为重复用户名冲突")


def test_login_wrong_password_401():
    user_dao = make_user_dao()
    asyncio.run(register(UserRegister(username="carol", email="c@x.com", password="pw123456"), user_dao))
    try:
        asyncio.run(login(UserLogin(username="carol", password="wrongpw"), user_dao))
    except AuthError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("错误密码应被拒绝")


def test_forgot_and_reset_password():
    user_dao = make_user_dao()
    user = asyncio.run(
        register(UserRegister(username="dave", email="d@x.com", password="oldpass1"), user_dao)
    )

    asyncio.run(forgot_password(ForgotPassword(email="d@x.com"), user_dao))

    reset_token = create_reset_token(user.id, user.email)
    asyncio.run(reset_password(ResetPassword(token=reset_token, new_password="newpass1"), user_dao))

    try:
        asyncio.run(login(UserLogin(username="dave", password="oldpass1"), user_dao))
    except AuthError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("旧密码应已失效")

    asyncio.run(login(UserLogin(username="dave", password="newpass1"), user_dao))


def test_forgot_password_unknown_email_raises():
    user_dao = make_user_dao()
    try:
        asyncio.run(forgot_password(ForgotPassword(email="nobody@x.com"), user_dao))
    except AuthError as e:
        assert e.status_code == 404
    else:
        raise AssertionError("未注册邮箱应提示未注册")


def test_reset_with_bad_token_fails():
    user_dao = make_user_dao()
    try:
        asyncio.run(
            reset_password(ResetPassword(token="not-a-valid-token", new_password="valid12"), user_dao)
        )
    except AuthError:
        pass
    else:
        raise AssertionError("无效 token 应被拒绝")


import asyncio

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.auth import AuthMiddleware
from app.pkgs.auth import create_access_token


def _make_request(path: str = "/chat", method: str = "POST", authorization: str | None = None) -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization else []
    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    return Request(scope, receive=None)


async def _call_next(request: Request) -> Response:
    return Response("ok")


def test_middleware_requires_token_on_protected_path():
    mw = AuthMiddleware(app=None)
    req = _make_request(path="/chat")
    resp = asyncio.run(mw.dispatch(req, _call_next))
    assert resp.status_code == 401


def test_middleware_allows_public_path_without_token():
    mw = AuthMiddleware(app=None)
    req = _make_request(path="/auth/login")
    resp = asyncio.run(mw.dispatch(req, _call_next))
    assert resp.status_code == 200


def test_middleware_sets_user_from_valid_token():
    mw = AuthMiddleware(app=None)
    token = create_access_token(123, "tokenuser", "t@x.com")
    req = _make_request(path="/chat", authorization=f"Bearer {token}")
    resp = asyncio.run(mw.dispatch(req, _call_next))
    assert resp.status_code == 200
    assert req.state.user.id == 123


def test_middleware_options_passthrough():
    mw = AuthMiddleware(app=None)
    req = _make_request(path="/chat", method="OPTIONS")
    resp = asyncio.run(mw.dispatch(req, _call_next))
    assert resp.status_code == 200
