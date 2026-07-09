from __future__ import annotations

import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.jwt import create_access_token, create_reset_token, decode_token
from app.auth.models import ForgotPassword, ResetPassword, UserLogin, UserRegister
from app.auth.password import hash_password, verify_password
from app.auth.service import AuthError, forgot_password, login, register, reset_password
from app.db.models import Base, User
from app.models import ChatRequest


def make_session():
    """用内存 SQLite 提供测试会话，隔离 MySQL 依赖。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_password_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_register_and_login_and_token():
    db = make_session()
    user = register(UserRegister(username="alice", email="a@x.com", password="pw123456"), db)
    assert user.username == "alice"

    token = login(UserLogin(username="alice", password="pw123456"), db)
    assert token.access_token

    payload = decode_token(token.access_token, expected_purpose="access")
    assert payload["user_id"] == user.id
    assert payload["username"] == "alice"
    assert payload["email"] == "a@x.com"


def test_duplicate_register_conflicts():
    db = make_session()
    register(UserRegister(username="bob", email="b@x.com", password="pw123456"), db)
    try:
        register(UserRegister(username="bob", email="other@x.com", password="pw123456"), db)
    except AuthError as e:
        assert e.status_code == 409
    else:
        raise AssertionError("应为重复用户名冲突")


def test_login_wrong_password_401():
    db = make_session()
    register(UserRegister(username="carol", email="c@x.com", password="pw123456"), db)
    try:
        login(UserLogin(username="carol", password="wrongpw"), db)
    except AuthError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("错误密码应被拒绝")


def test_forgot_and_reset_password():
    db = make_session()
    user = register(UserRegister(username="dave", email="d@x.com", password="oldpass1"), db)

    # 找回：用户存在则发出 reset token
    forgot_password(ForgotPassword(email="d@x.com"), db)

    # 直接构造 reset token 走 service 验证流程
    reset_token = create_reset_token(user.id, user.email)
    reset_password(ResetPassword(token=reset_token, new_password="newpass1"), db)

    # 旧密码失效、新密码可用
    try:
        login(UserLogin(username="dave", password="oldpass1"), db)
    except AuthError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("旧密码应已失效")

    login(UserLogin(username="dave", password="newpass1"), db)


def test_forgot_password_unknown_email_no_error():
    db = make_session()
    # 不存在的邮箱不抛错（模糊处理）
    forgot_password(ForgotPassword(email="nobody@x.com"), db)


def test_reset_with_bad_token_fails():
    db = make_session()
    try:
        reset_password(ResetPassword(token="not-a-valid-token", new_password="valid12"), db)
    except AuthError:
        pass
    else:
        raise AssertionError("无效 token 应被拒绝")


def test_get_request_user_prefers_token():
    # 模拟 app/api/app.py 的 get_request_user 逻辑（纯函数，可单独验证）
    from app.api.app import get_request_user

    token = create_access_token("u-123", "tokenuser", "t@x.com")
    req = ChatRequest(session_id="s1", user_id="body-user", message="hi", channel="web")
    assert get_request_user(req, f"Bearer {token}") == "u-123"


def test_get_request_user_falls_back_to_body():
    from app.api.app import get_request_user

    req = ChatRequest(session_id="s1", user_id="body-user", message="hi", channel="web")
    # 无 token
    assert get_request_user(req, None) == "body-user"
    # token 无法解析
    assert get_request_user(req, "Bearer garbage") == "body-user"
