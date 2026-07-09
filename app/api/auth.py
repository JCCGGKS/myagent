from __future__ import annotations

from app.business.auth.router import router

# 认证路由（register/login/forgot-password/reset-password/me）统一定义在
# business/auth/router.py（前缀 /auth），此处直接挂载。
router = router
