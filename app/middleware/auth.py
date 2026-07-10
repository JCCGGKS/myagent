from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.schema.auth import UserInfo
from app.pkgs.auth import JWTError, decode_token

# 无需登录的公开路径：获取 token 的入口与 API 文档。
PUBLIC_PATHS = {
    "/auth/register",
    "/auth/login",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """认证第一道关：解析 Authorization Bearer token 并写入 request.state.user。

    - 非公开路径缺失或无效 token 直接返回 401（注意：BaseHTTPMiddleware 位于
      FastAPI 的 ExceptionMiddleware 之外，必须自行返回 401 响应，不能 raise
      HTTPException，否则会被 ServerErrorMiddleware 转成 500）；
    - 公开路径（登录/注册等）放行，由具体接口自行处理；
    - OPTIONS 预检放行，避免浏览器 CORS 预检被 401 拦截。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        user: UserInfo | None = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                payload = decode_token(token, expected_purpose="access")
                user = UserInfo(
                    id=int(payload.get("user_id", 0)),
                    username=str(payload.get("username", "")),
                    email=str(payload.get("email", "")),
                )
            except JWTError:
                user = None

        request.state.user = user

        if user is None and request.url.path not in PUBLIC_PATHS:
            return JSONResponse(
                status_code=401,
                content={"detail": "未提供或无效的认证 token"},
            )

        return await call_next(request)
