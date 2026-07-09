# 认证模块（app/business/auth）

平台用户的注册、登录、找回密码与身份解析。基于 JWT（HS256）+ bcrypt 密码哈希，无服务端 session。

## 目录结构

```
app/business/auth/
├── __init__.py     # 导出 router
├── models.py       # Pydantic 请求/响应模型
├── service.py      # 业务逻辑
├── deps.py         # FastAPI 依赖：get_current_user
├── router.py       # /auth 路由定义
└── README.md       # 本文档
```

工具实现位于 `app/pkgs/auth/`（`jwt.py` / `password.py` / `email.py`），数据访问走 `app/dao/user.py`（`UserDAO`）。

## 接口清单

所有接口前缀 `/auth`。

| 方法 | 路径 | 鉴权 | 说明 | 请求体 | 响应 |
|---|---|---|---|---|---|
| POST | `/auth/register` | 公开 | 开放注册 | `UserRegister` | `UserInfo` (201) |
| POST | `/auth/login` | 公开 | 用户名+密码登录，返回 token + 用户信息 | `UserLogin` | `LoginResponse` |
| POST | `/auth/forgot-password` | 公开 | 忘记密码：按邮箱发重置链接 | `ForgotPassword` | `{"detail": "..."}` |
| POST | `/auth/reset-password` | 公开 | 凭 reset token 重置密码 | `ResetPassword` | `{"detail": "..."}` |
| POST | `/auth/change-password` | **需登录** | 登录后修改密码（验证旧密码） | `ChangePassword` | `{"detail": "..."}` |

### 两个"改密码"接口的区别

| 接口 | 场景 | 凭证 | 鉴权 |
|---|---|---|---|
| `/auth/reset-password` | **忘记密码**（未登录，通过邮箱找回） | 邮箱收到的 reset token | 公开 |
| `/auth/change-password` | **登录后主动改密** | 原密码 | 需 Authorization 头 |

### 请求/响应模型（`models.py`）

- `UserRegister`: `username(3-64)` / `email(带格式校验)` / `password(6-128)`
- `UserLogin`: `username` / `password`
- `ForgotPassword`: `email(带格式校验)`
- `ResetPassword`: `token` / `new_password(6-128)`
- `ChangePassword`: `old_password` / `new_password(6-128)`
- `LoginResponse`: `access_token` / `token_type="bearer"` / `user: UserInfo`
- `UserInfo`: `id(int)` / `username` / `email`

## 关键流程

### 注册
1. 校验 username / email 唯一（冲突 → 409）
2. bcrypt 哈希密码
3. 写入 DB，返回 `UserInfo`

### 登录
1. 按 username 查用户
2. bcrypt 校验密码（失败 → 401）
3. 签发 access token（payload 含 `user_id`/`username`/`email`，`sub` 为字符串形式）
4. **直接返回 token + 用户信息**（前端无需再请求 `/auth/me`）

### 忘记密码 → 重置（两步，独立接口）
1. `POST /auth/forgot-password` { email }
   - 用户存在才签发 reset token（`purpose=reset`，默认 15 分钟过期）
   - 通过 SMTP 发送重置链接（`smtp.enabled=false` 时仅打印到日志）
   - **无论用户是否存在均返回成功**（不泄露账号存在性）
2. `POST /auth/reset-password` { token, new_password }
   - 解码 reset token，校验 `purpose=reset` 与 `exp`
   - 按 `user_id` 查用户 → 更新 `password_hash`

### 登录后修改密码
1. `POST /auth/change-password` { old_password, new_password }（需 `Authorization` 头）
2. 验证原密码（失败 → 400）
3. 更新 `password_hash`
4. 前端收到成功后清除登录态，跳转登录页重新登录

### 身份解析（`get_current_user`）
- 从 `Authorization: Bearer <token>` 解析 access token
- 校验 `purpose=access` 与签名/过期
- 失败 → 401
- 用于 `/auth/change-password` 及其它需登录的接口

## JWT 配置

读取 `config/llm_config.{env}.yml` 的 `jwt:` 段：

```yaml
jwt:
  secret: "<强随机值>"          # 生产务必替换，≥32 字节
  algorithm: "HS256"
  access_expire_minutes: 1440   # 登录 token 有效期
  reset_expire_minutes: 15      # 找回密码 token 有效期
```

- access token payload: `sub=str(user_id)` / `user_id(int)` / `username` / `email` / `purpose=access` / `iat` / `exp`
- reset token payload: `sub=str(user_id)` / `user_id(int)` / `email` / `purpose=reset` / `iat` / `exp`
- `sub` 遵循 JWT 规范存字符串（供第三方工具识别），`user_id` 保留原始 int（供业务代码直接使用）

## SMTP 配置

读取 `config/llm_config.{env}.yml` 的 `smtp:` 段：

```yaml
smtp:
  enabled: false        # 关闭时仅打印重置链接到日志
  host: ""
  port: 465
  user: ""
  password: ""
  from_addr: "no-reply@myagent.local"
  use_tls: true
```

## 数据依赖

- 表 `users`（见 `template/sqls/01_users.sql`）：`id(BIGINT 自增主键)` / `username(唯一)` / `email(唯一)` / `password_hash` / `created_at` / `updated_at`
- DAO 层 `UserDAO`（`app/dao/user.py`）抽象，提供 `get_by_username` / `get_by_email` / `get_by_id` / `create` / `update_password`

## 分层说明

```
router.py   →  接口定义、HTTP 错误转换
   ↓
service.py  →  业务规则（AuthError 携带状态码）
   ↓
pkgs/auth   →  纯工具（JWT 签发/解码、bcrypt、SMTP）
dao/user    →  数据访问（抽象 + 多实现）
```

`service.py` 不直接操作 DB，只依赖 `UserDAO` 抽象，便于切换存储实现（内存/MySQL/其它）。

## 前端对接

- 前端 `frontend/src/lib/api.ts` 提供 `postRegister` / `postLogin` / `postForgotPassword` / `postResetPassword` / `postChangePassword`。
- `request()` 自动从 `localStorage` 注入 `Authorization: Bearer <token>`。
- **登录即返回用户信息**，前端存入 `localStorage`（key `myagent_user`），无需二次请求。
- **401 拦截**：API 返回 401 时自动清除登录态并跳转 `/login`（覆盖 token 过期场景）。
- Pinia store `frontend/src/stores/auth.ts` 管理 `token` / `user` / `login` / `register` / `logout`。
- 路由守卫：未登录访问非 auth 页面 → 跳转 `/login`；已登录访问 auth 页面 → 跳转 `/`。
- 找回密码页面（`ForgotPasswordView.vue`）为同页两步式：输入邮箱发链接 → 输入 token + 新密码重置。
- 修改密码弹窗在 `ConsoleView.vue` 侧边栏用户区，成功后清除登录态跳转登录页。
