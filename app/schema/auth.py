"""认证相关 Pydantic 请求/响应模型。

按职责归属到 schema 层（Pydantic 结构属于 schema 职责，而非业务逻辑）。
请求模型：`UserRegister` / `UserLogin` / `ForgotPassword` / `ResetPassword` /
`ChangePassword`；响应/凭证模型：`Token` / `UserInfo` / `LoginResponse`。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("邮箱格式不合法")
        return v


class UserLogin(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ForgotPassword(BaseModel):
    email: str = Field(min_length=1, max_length=255)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("邮箱格式不合法")
        return v


class ResetPassword(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=128)


class ChangePassword(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    username: str
    email: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo
