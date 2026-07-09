from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.business.auth.models import UserInfo
from app.pkgs.auth import JWTError, decode_token


class AuthMiddleware(BaseHTTPMiddleware):
    """解析 Authorization Bearer token，将当前用户挂载到 request.state.user。

    该中间件对缺失或无效 token 不抛异常（保留 request.state.user = None），
    由具体接口通过 `get_current_user` 等依赖决定是否要求登录。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.user = None
        authorization = request.headers.get("authorization", "")
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                payload = decode_token(token, expected_purpose="access")
                request.state.user = UserInfo(
                    id=int(payload.get("user_id", 0)),
                    username=str(payload.get("username", "")),
                    email=str(payload.get("email", "")),
                )
            except JWTError:
                # token 无效时保持未登录状态，由依赖层决定 401
                pass
        return await call_next(request)
