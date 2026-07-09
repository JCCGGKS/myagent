from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.business.auth.models import ForgotPassword, ResetPassword, UserLogin, UserRegister
from app.business.auth.service import (
    AuthError,
    forgot_password,
    login,
    register,
    reset_password,
)
from app.dao import SqlUserDAO
from app.model import Base, user  # noqa: F401  (确保 User 表注册到 Base.metadata)
from app.schema import ChatRequest
from app.pkgs.auth import (
    create_access_token,
    create_reset_token,
    decode_token,
    hash_password,
    verify_password,
)


def make_user_dao():
    """用内存 SQLite 提供测试 DAO，隔离 MySQL 依赖。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return SqlUserDAO(Session)


def test_password_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_register_and_login_and_token():
    user_dao = make_user_dao()
    user = register(UserRegister(username="alice", email="a@x.com", password="pw123456"), user_dao)
    assert user.username == "alice"

    token = login(UserLogin(username="alice", password="pw123456"), user_dao)
    assert token.access_token

    payload = decode_token(token.access_token, expected_purpose="access")
    assert payload["user_id"] == user.id
    assert payload["username"] == "alice"
    assert payload["email"] == "a@x.com"


def test_duplicate_register_conflicts():
    user_dao = make_user_dao()
    register(UserRegister(username="bob", email="b@x.com", password="pw123456"), user_dao)
    try:
        register(UserRegister(username="bob", email="other@x.com", password="pw123456"), user_dao)
    except AuthError as e:
        assert e.status_code == 409
    else:
        raise AssertionError("应为重复用户名冲突")


def test_login_wrong_password_401():
    user_dao = make_user_dao()
    register(UserRegister(username="carol", email="c@x.com", password="pw123456"), user_dao)
    try:
        login(UserLogin(username="carol", password="wrongpw"), user_dao)
    except AuthError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("错误密码应被拒绝")


def test_forgot_and_reset_password():
    user_dao = make_user_dao()
    user = register(UserRegister(username="dave", email="d@x.com", password="oldpass1"), user_dao)

    forgot_password(ForgotPassword(email="d@x.com"), user_dao)

    reset_token = create_reset_token(user.id, user.email)
    reset_password(ResetPassword(token=reset_token, new_password="newpass1"), user_dao)

    try:
        login(UserLogin(username="dave", password="oldpass1"), user_dao)
    except AuthError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("旧密码应已失效")

    login(UserLogin(username="dave", password="newpass1"), user_dao)


def test_forgot_password_unknown_email_no_error():
    user_dao = make_user_dao()
    forgot_password(ForgotPassword(email="nobody@x.com"), user_dao)


def test_reset_with_bad_token_fails():
    user_dao = make_user_dao()
    try:
        reset_password(ResetPassword(token="not-a-valid-token", new_password="valid12"), user_dao)
    except AuthError:
        pass
    else:
        raise AssertionError("无效 token 应被拒绝")


def test_get_request_user_prefers_token():
    from app.api.chat import get_request_user

    token = create_access_token("u-123", "tokenuser", "t@x.com")
    req = ChatRequest(session_id="s1", user_id="body-user", message="hi", channel="web")
    assert get_request_user(req, f"Bearer {token}") == "u-123"


def test_get_request_user_falls_back_to_body():
    from app.api.chat import get_request_user

    req = ChatRequest(session_id="s1", user_id="body-user", message="hi", channel="web")
    assert get_request_user(req, None) == "body-user"
    assert get_request_user(req, "Bearer garbage") == "body-user"
